"""Selected dimensioned candidate overlays; all 182 individual SVGs also exist."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
def run():
    rows=json.loads((ROOT/'phase2e/results/validation-records.json').read_text())['records'][2:]
    indices=[0,118,min(range(len(rows)),key=lambda i:rows[i]['areaTopologyDifferences']['marginalAllCandidatesScenario']['copperAreaDeltaMm2'])]
    fig,axs=plt.subplots(1,3,figsize=(16,6),dpi=220)
    for ax,index in zip(axs,indices):
        r=rows[index];pts=r['originalGeometry']['contours'][0]['points'];cand=r['proposedRecoveryGeometry']
        ax.plot([p[0]/1e5 for p in pts],[p[1]/1e5 for p in pts],color='#1761a5',lw=1.5,label='Original open contour')
        end,start=cand['edgeTicks'];ax.plot([end[0]/1e5,start[0]/1e5],[end[1]/1e5,start[1]/1e5],color='#d32620',ls='--',lw=1.8,label='Unapproved closing candidate')
        ax.set_title(f'Laser region {index} — BLOCKED\nGap {cand["gapLengthMm"]:.6f} mm; lines {r["sourceCommandRange"]["firstLine"]}–{r["sourceCommandRange"]["lastLine"]}')
        ax.set_xlabel('X (mm)');ax.set_ylabel('Y (mm)');ax.axis('equal');ax.grid(lw=.3);ax.legend(fontsize=8)
    fig.suptitle('Diagnostic candidates only — geometric closure does not prove native EasyEDA design intent')
    fig.tight_layout();fig.savefig(ROOT/'phase2e/results/overlays/selected-laser-candidates.png');plt.close(fig)
if __name__=='__main__':run()
