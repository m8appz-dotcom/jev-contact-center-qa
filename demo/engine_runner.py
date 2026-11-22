from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from jevqa.jev_client import JevClient,ErrorJev
from jevqa.rubric import load_rubric,build_request,parse_response
from jevqa.scoring import calificar
from jevqa.anonymize import anonymize
data=json.load(sys.stdin)
rubric=load_rubric(str(ROOT/'rubrics/support_en.json'))
text=anonymize(data['text'],names=data.get('names',[]))
try:
    raw=JevClient(intentos=1,tiempo_limite=60).evaluar(build_request(rubric,text,modelo='jev-latest'))
    score=calificar(rubric,parse_response(rubric,raw))
    labels={i['id']:i['label'] for i in json.loads((ROOT/'rubrics/support_en.json').read_text())['items']}
    result={'language':'en','conversation':data['id'],'model':raw.get('model','jev-latest'),'score':score['nota'],'outcome':'Pass' if score['estado']=='aprobado' else 'Needs attention','humanReviewRequired':score['revisar'],'criteria':[{'label':labels[k],'meets':v['cumple'],'critical':v['critico'],'weight':v['peso'],'probability':v['probabilidad'],'confidence':v['confianza'],'needsReview':bool(v['motivos_revision'])} for k,v in score['items'].items()],'usage':raw.get('usage',{}),'scope':'Model assessment of an authored example. Human review remains separate.'}
    print(json.dumps(result))
except ErrorJev as exc:
    print(json.dumps({'error':{'code':'provider_unavailable','message':'JEV could not evaluate this example. Your manual review is safe.'}}))
