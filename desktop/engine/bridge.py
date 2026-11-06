"""Versioned JSONL bridge for DemonX PCB Prep. The Electron main process owns this child."""
from __future__ import annotations
import json, math, os, sys, threading, uuid
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "phase2g"))
sys.path.insert(0, str(ROOT))
from pcbprep.inspection_model import load_archive
from extract_fixtures import OUT as EXTRACTION_ROOT
from phase2l.geometry import VBit, eligibility_for_simulation, plan_isolation
from phase2o.isolation import identify_residual_candidates, plan_selective_clearing, plan_two_pass

PROTOCOL = "demonx.pcbprep.engine/1"
MAX_INPUT = 128 * 1024
MAX_OUTPUT = 32 * 1024 * 1024
MAX_ARCHIVE = 64 * 1024 * 1024
write_lock = threading.Lock()
active_lock = threading.Lock()
active: dict | None = None
current_document = None
stopping = False

class Cancelled(Exception): pass

def emit(value: dict) -> None:
    line = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(line.encode("utf-8")) > MAX_OUTPUT:
        raise ValueError("ENGINE_RESPONSE_TOO_LARGE")
    with write_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

def check_cancel(event: threading.Event) -> None:
    if event.is_set(): raise Cancelled("Operation cancelled")

def number(value, name: str, lo: float, hi: float) -> float:
    if isinstance(value, bool): raise ValueError(f"{name}_MUST_BE_NUMBER")
    try: result = float(value)
    except (TypeError, ValueError): raise ValueError(f"{name}_MUST_BE_NUMBER")
    if not math.isfinite(result) or not lo <= result <= hi: raise ValueError(f"{name}_OUT_OF_RANGE")
    return result

def path_data(geometry, *, invert_y=True) -> str:
    if geometry is None or geometry.is_empty: return ""
    pieces=[]
    def coords_path(coords, close=False):
        pts=list(coords)
        if not pts: return
        def xy(p): return (format(float(p[0]), ".12g"), format(-float(p[1]) if invert_y else float(p[1]), ".12g"))
        x,y=xy(pts[0]); pieces.append(f"M{x},{y}")
        for p in pts[1:]:
            x,y=xy(p); pieces.append(f"L{x},{y}")
        if close: pieces.append("Z")
    def visit(g):
        if g.is_empty: return
        t=g.geom_type
        if t=="Polygon":
            coords_path(g.exterior.coords, True)
            for ring in g.interiors: coords_path(ring.coords, True)
        elif t in ("MultiPolygon","GeometryCollection","MultiLineString"):
            for item in g.geoms: visit(item)
        elif t in ("LineString","LinearRing"): coords_path(g.coords, False)
        elif t=="Point":
            x,y=g.x,(-g.y if invert_y else g.y)
            pieces.append(f"M{x:.12g},{y:.12g}L{x + 0.0001:.12g},{y:.12g}")
    visit(geometry)
    return "".join(pieces)

def layer_manifest(doc):
    rows=[]
    for layer in doc.canonical_geometry.layers:
        geom=layer.geometry
        rows.append({"name":layer.name,"side":layer.side,"polarity":layer.polarity,
                     "role":layer.role,"provenance":[list(x) for x in layer.provenance],
                     "approximationErrorBoundMm":layer.approximation_error_bound_mm,
                     "boundsMm":list(geom.bounds) if geom is not None and not geom.is_empty else None,
                     "path":path_data(geom)})
    return rows

def plain(value):
    if isinstance(value, Mapping): return {str(k):plain(v) for k,v in value.items()}
    if isinstance(value, (tuple,list)): return [plain(v) for v in value]
    if value is None or isinstance(value,(str,int,float,bool)): return value
    return str(value)
def board_payload(doc):
    check=os.environ.get("DEMONX_PCBPREP_MAX_OUTPUT_MB")
    layers=layer_manifest(doc)
    bounds=doc.bounds
    drills=[{"xMm":float(h.get("xMm",0)),"yMm":float(h.get("yMm",0)),
             "diameterMm":float(h.get("sourceDiameterMm") or 0),
             "group":str(h.get("group","unassigned")),"sourceFile":str(h.get("sourceFile","")),
             "plating":str(h.get("platingClassification","unknown"))} for h in doc.hits]
    slots=[{"coordinatesMm":s.get("coordinatesMm",[]),"diameterMm":float(s.get("sourceDiameterMm") or 0),
            "sourceFile":str(s.get("sourceFile",""))} for s in doc.slots]
    regions=[{"index":r.index,"sourceFile":r.source_file,"sourceSha256":r.source_sha256,
              "firstLine":r.first_line,"lastLine":r.last_line,"polarity":r.polarity,
              "issue":r.issue,"closureLengthMm":r.closure_length_mm,
              "recoveryStatus":r.recovery_status,"requiredUserAction":r.required_user_action}
             for r in doc.regions]
    provenance={}
    for layer in doc.layer_files:
        provenance[layer.name]={"label":layer.label,"kind":layer.kind,
            "sha256":layer.metadata.get("sha256"),"featureCount":len(layer.features),
            "unresolvedCount":layer.metadata.get("unresolvedCount",0),
            "sourceConformance":layer.metadata.get("sourceConformance")}
    findings=[{"category":"SOURCE FINDING","message":s,"operation":"full-archive"} for s in doc.issues]
    for region in doc.regions:
        findings.append({"category":"SOURCE REGION · " + region.recovery_status,
            "message":f"{region.source_file} lines {region.first_line}–{region.last_line}: {region.issue}; polarity {region.polarity}; closure length {region.closure_length_mm:.9f} mm.",
            "operation":"copper-isolation","sourceFile":region.source_file,"firstLine":region.first_line,
            "lastLine":region.last_line,"requiredUserAction":region.required_user_action})
    for layer in doc.layer_files:
        unresolved=int(layer.metadata.get("unresolvedCount",0) or 0)
        unsupported=len(layer.metadata.get("unsupportedObjects",[]) or [])
        if unresolved:
            operation="outline-cutting" if layer.kind=="profile" else "copper-isolation" if layer.kind in ("top","bottom") else "full-archive"
            findings.append({"category":"NEEDS VERIFICATION","message":f"{layer.name}: {unresolved} parser warnings or unresolved source features.","operation":operation,"sourceFile":layer.name})
        if unsupported:
            findings.append({"category":"NEEDS VERIFICATION","message":f"{layer.name}: {unsupported} unsupported drill records.","operation":"drilling","sourceFile":layer.name})
    if doc.profile_geometry is None or doc.profile_geometry.is_empty:
        findings.append({"category":"BLOCKED","message":"Board outline is missing or empty; outline preparation remains blocked.","operation":"outline-cutting"})
    source_features=[plain(feature) for feature in doc.canonical_geometry.source_features]
    payload={"protocol":PROTOCOL,"boardId":doc.board_id,"archiveSha256":doc.archive_sha256,
       "boundsMm":list(bounds) if bounds else None,"layers":layers,"drills":drills,"slots":slots,
       "regions":regions,"sourceFiles":provenance,"findings":findings,"sourceFeatures":source_features,
       "sourceCompliance":doc.source_compliance,"validation":{
          "sourceConformance":doc.canonical_geometry.source_conformance,
          "independentVerification":doc.canonical_geometry.independent_verification,
          "machiningEligibility":doc.canonical_geometry.machining_eligibility,
          "units":doc.canonical_geometry.units,"coordinateFrame":doc.canonical_geometry.coordinate_frame,
          "contentHash":doc.canonical_geometry.content_hash},
       "geometryStatus":"Inspection-only; geometry and simulation are diagnostic.",
       "limits":{"sourceFeatureCount":len(doc.canonical_geometry.source_features),
                 "drillFeatureCount":len(doc.canonical_geometry.drill_features)}}
    return payload

def simulation_payload(doc, args, cancel_event):
    allowed, reason=eligibility_for_simulation(doc.canonical_geometry, inspection_only=True)
    if not allowed: raise ValueError(reason)
    check_cancel(cancel_event)
    material=doc.canonical_geometry.material("bottom-copper")
    cutter=VBit(number(args.get("angleDeg",30),"ANGLE",1,179),number(args.get("tipDiameterMm",.1),"TIP_DIAMETER",0,5))
    depth=number(args.get("depthMm",.1),"DEPTH",0,2)
    mode=args.get("mode","single")
    if mode not in ("single","two-pass","selective-clearing"): raise ValueError("UNKNOWN_SIMULATION_MODE")
    single=plan_isolation(material,cutter,depth,approximation_error_bound_mm=.002)
    check_cancel(cancel_event)
    base={"mode":mode,"manufacturingEligibility":doc.canonical_geometry.machining_eligibility,
          "inspectionOnly":True,"manufacturingAuthorized":False,"effectiveWidthMm":single.effective_width_mm,
          "centerlineOffsetMm":single.centerline_offset_mm,"singlePass":{"path":path_data(single.center_paths),
          "contours":len(getattr(single.center_paths,"geoms",[])),"lengthMm":single.center_paths.length,
          "unfitPath":path_data(single.unfit_clearances),"intrusionPath":path_data(single.copper_intrusion),
          "uncertaintyPath":path_data(single.geometry_uncertainty),
          "issues":[{"category":x.category,"cause":x.cause,"requiredClearanceMm":x.required_clearance_mm,
                      "measuredClearanceMm":x.measured_clearance_mm,"areaMm2":x.raw_area_mm2}
                     for x in single.issues]}}
    if mode=="two-pass":
        offset=number(args.get("additionalOffsetMm",.2),"ADDITIONAL_OFFSET",.005,1)
        p=plan_two_pass(material,cutter,depth,offset,approximation_error_bound_mm=.002,baseline_plan=single)
        base.update({"additionalOffsetMm":p.additional_offset_mm,"candidateLengthMm":p.candidate_length_mm,
          "acceptedLengthMm":p.accepted_length_mm,"rejectedLengthMm":p.rejected_length_mm,
          "topologyWithheldLengthMm":p.topology_withheld_length_mm,
          "incrementalSweptAreaMm2":p.incremental_swept_area_mm2,
          "incrementalCopperRemovalMm2":p.incremental_copper_removal_mm2,
          "pass2Path":path_data(p.accepted_paths),"rejectedPath":path_data(p.rejected_paths),
          "rejectedFootprintPath":path_data(p.rejected_footprint),
          "rejections":[{"category":x.category,"cause":x.message,"lengthMm":x.path.length,
             "protectedOverlapMm2":x.protected_overlap.area} for x in p.rejections]})
    elif mode=="selective-clearing":
        residual=material.difference(single.cutting_footprint)
        candidates=identify_residual_candidates(residual)
        selected=args.get("selectedIds",[])
        if not isinstance(selected,list) or len(selected)>100 or any(not isinstance(x,str) for x in selected):
            raise ValueError("INVALID_SELECTED_IDS")
        selected=[x for x in selected if x in {c.candidate_id for c in candidates}]
        p=plan_selective_clearing(material,candidates,selected,cutter=cutter,depth_mm=depth,
            classified_for_preview=selected,approximation_error_bound_mm=.002)
        base.update({"candidates":[{"id":c.candidate_id,"areaMm2":c.area_mm2,"path":path_data(c.geometry)} for c in candidates],
          "selectedIds":list(p.selected_ids),"acceptedPath":path_data(p.accepted_paths),
          "rejectedPath":path_data(p.rejected_paths),"rejectedFootprintPath":path_data(p.rejected_footprint),
          "remainingSelectedAreaMm2":p.remaining_selected_copper.area,
          "clearedAreaMm2":p.cleared_area_mm2,
             "rejections":[{"category":x.category,"cause":x.message,"protectedOverlapMm2":x.protected_overlap.area} for x in p.rejections]})
    check_cancel(cancel_event)
    return base

def run_request(req, cancel_event):
    global current_document
    rid=req.get("requestId")
    if not isinstance(rid,str) or len(rid)>80: raise ValueError("INVALID_REQUEST_ID")
    if req.get("protocol")!=PROTOCOL: raise ValueError("UNSUPPORTED_PROTOCOL_VERSION")
    command=req.get("command")
    if command=="open":
        raw=req.get("archivePath")
        if not isinstance(raw,str) or len(raw)>32768: raise ValueError("INVALID_ARCHIVE_PATH")
        p=Path(raw)
        if p.suffix.lower()!=".zip" or not p.is_file() or p.stat().st_size>MAX_ARCHIVE: raise ValueError("ARCHIVE_NOT_ALLOWED_OR_TOO_LARGE")
        EXTRACTION_ROOT.mkdir(parents=True, exist_ok=True)
        def progress(message):
            check_cancel(cancel_event)
            emit({"protocol":PROTOCOL,"requestId":rid,"event":"progress","message":str(message)[:500]})
        doc=load_archive(p,progress=progress)
        check_cancel(cancel_event)
        old=current_document; current_document=doc
        if old is not None: old.close()
        return board_payload(doc)
    if command=="simulate":
        if current_document is None: raise ValueError("NO_BOARD_LOADED")
        return simulation_payload(current_document,req.get("options",{}),cancel_event)
    if command=="shutdown": return {"shutdown":True}
    raise ValueError("UNKNOWN_COMMAND")

def worker(req, event):
    global active,stopping
    rid=req.get("requestId","unknown")
    try:
        result=run_request(req,event)
        if req.get("command")=="shutdown": stopping=True
        emit({"protocol":PROTOCOL,"requestId":rid,"event":"result","result":result})
    except Cancelled as exc:
        emit({"protocol":PROTOCOL,"requestId":rid,"event":"cancelled","message":str(exc)})
    except Exception as exc:
        emit({"protocol":PROTOCOL,"requestId":rid,"event":"error","error":{"code":str(exc.args[0])[:120] if isinstance(exc,ValueError) and exc.args else "ENGINE_ERROR","message":str(exc)[:1000]}})
    finally:
        with active_lock: active=None

def main():
    global active,stopping,current_document
    emit({"protocol":PROTOCOL,"event":"ready","engine":"pcbprep-python","readOnly":True})
    for raw in sys.stdin.buffer:
        if len(raw)>MAX_INPUT:
            emit({"protocol":PROTOCOL,"event":"error","error":{"code":"REQUEST_TOO_LARGE","message":"Request exceeds size limit"}}); continue
        try: req=json.loads(raw.decode("utf-8"))
        except Exception:
            emit({"protocol":PROTOCOL,"event":"error","error":{"code":"INVALID_JSON","message":"Request is not valid UTF-8 JSON"}}); continue
        if not isinstance(req,dict):
            emit({"protocol":PROTOCOL,"event":"error","error":{"code":"INVALID_REQUEST","message":"Request must be an object"}}); continue
        if req.get("command")=="cancel":
            with active_lock:
                if active and req.get("targetRequestId")==active[0]: active[1].set()
            emit({"protocol":PROTOCOL,"requestId":str(req.get("requestId",""))[:80],"event":"result","result":{"cancelRequested":True}})
            continue
        with active_lock:
            if active is not None:
                emit({"protocol":PROTOCOL,"requestId":str(req.get("requestId",""))[:80],"event":"error","error":{"code":"ENGINE_BUSY","message":"Another geometry operation is active"}}); continue
            event=threading.Event(); active=(req.get("requestId"),event)
        threading.Thread(target=worker,args=(req,event),daemon=False).start()
        if stopping: break
    with active_lock:
        pending = active
    if pending: pending[1].set()
    while True:
        with active_lock: busy = active is not None
        if not busy: break
        threading.Event().wait(.05)
    if current_document is not None: current_document.close()

if __name__=="__main__": main()
