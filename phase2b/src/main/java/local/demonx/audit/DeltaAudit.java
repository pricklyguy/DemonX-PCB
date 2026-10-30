package local.demonx.audit;

import com.deltaproto.deltagerber.model.drill.*;
import com.deltaproto.deltagerber.model.gerber.*;
import com.deltaproto.deltagerber.model.gerber.operation.GraphicsObject;
import com.deltaproto.deltagerber.parser.ExcellonParser;
import com.deltaproto.deltagerber.parser.GerberParser;
import java.nio.file.*;
import java.util.*;

public final class DeltaAudit {
  private static String q(String s) { return "\"" + s.replace("\"", "\"\"") + "\""; }
  private static String n(double v) { return String.format(Locale.ROOT, "%.9f", v); }
  public static void main(String[] args) throws Exception {
    Path root=Path.of(args[0]), out=Path.of(args[1]);
    List<String> rows=new ArrayList<>();
    rows.add("kind,sourceFile,recordType,recordIndex,toolId,diameterMm,x1Mm,y1Mm,x2Mm,y2Mm,minX,minY,maxX,maxY,warningCount,warnings");
    try (var paths=Files.walk(root)) {
      for (Path p: paths.filter(Files::isRegularFile).sorted().toList()) {
        String name=p.getFileName().toString(), upper=name.toUpperCase(Locale.ROOT);
        String text=Files.readString(p);
        if (upper.endsWith(".DRL") || upper.endsWith(".TXT") || upper.endsWith(".XLN")) {
          DrillDocument d=new ExcellonParser().parse(text);
          Map<String,Integer> counts=new TreeMap<>(); int index=0;
          for (DrillOperation op:d.getOperations()) {
            String type=op instanceof DrillHit ? "DrillHit" : op instanceof DrillSlot ? "DrillSlot" : op.getClass().getSimpleName();
            counts.merge(type,1,Integer::sum); BoundingBox b=op.getBoundingBox(); Tool t=op.getTool();
            String x1="",y1="",x2="",y2="";
            if(op instanceof DrillHit h){x1=n(h.getX());y1=n(h.getY());}
            if(op instanceof DrillSlot s){x1=n(s.getStartX());y1=n(s.getStartY());x2=n(s.getEndX());y2=n(s.getEndY());}
            rows.add(String.join(",", "drill",q(root.relativize(p).toString()),q(type),Integer.toString(index++),
              t==null?"":Integer.toString(t.getNumber()),t==null?"":n(t.getDiameter()),x1,y1,x2,y2,
              n(b.getMinX()),n(b.getMinY()),n(b.getMaxX()),n(b.getMaxY()),Integer.toString(d.getWarnings().size()),q(String.join(" | ",d.getWarnings()))));
          }
          if(d.getOperations().isEmpty()) rows.add(String.join(",", "drill",q(root.relativize(p).toString()),q("EMPTY"),"","","","","","","","","","","",Integer.toString(d.getWarnings().size()),q(String.join(" | ",d.getWarnings()))));
        } else if (upper.endsWith(".GTL") || upper.endsWith(".GBL") || upper.endsWith(".GTS") || upper.endsWith(".GBS") || upper.endsWith(".GTO") || upper.endsWith(".GBO") || upper.endsWith(".GTP") || upper.endsWith(".GBP") || upper.endsWith(".GKO") || upper.endsWith(".GML") || upper.endsWith(".GM1") || upper.endsWith(".GM") || upper.endsWith(".GDL") || upper.endsWith(".GDD")) {
          GerberDocument d=new GerberParser().parse(text); int index=0;
          for (GraphicsObject o:d.getObjects()) {
            BoundingBox b=o.getBoundingBox();
            rows.add(String.join(",", "gerber",q(root.relativize(p).toString()),q(o.getClass().getSimpleName()),Integer.toString(index++),"","","","","","",
              n(b.getMinX()),n(b.getMinY()),n(b.getMaxX()),n(b.getMaxY()),Integer.toString(d.getWarnings().size()),q(String.join(" | ",d.getWarnings()))));
          }
        }
      }
    }
    Files.createDirectories(out.getParent()); Files.write(out,rows);
  }
}
