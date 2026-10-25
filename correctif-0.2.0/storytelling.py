"""Narration v2: un evenement, trois propositions, une revision, puis production."""
import json
from pydantic import Field
from .schemas import Strict,Script
from .core import ReviewNeeded
from .editorial import Narrative,VisualPlan,word_count,fingerprint

class Selection(Strict):
    selected: int = Field(ge=1,le=3)
    reason: str
    corrections: list[str]

class Direction(Strict):
    action_period: str
    location: str
    main_object: str
    character_appearance: str
    style: str
    avoid: list[str]

def errors(draft,dossier):
    ids={c['id'] for c in dossier['claims']}
    problems=[]
    if not 80<=word_count(draft)<=200:problems.append('Longueur technique: 80 a 200 mots, sans remplissage')
    if [s['id'] for s in draft['scenes']]!=list(range(1,len(draft['scenes'])+1)):problems.append('Numerotation 1..N')
    for s in draft['scenes']:
        if not s['narration'].strip() or not set(s['claim_ids'])<=ids:problems.append('Texte vide ou reference inconnue')
    return problems

def cached(ctx,path,schema,make):
    target=ctx.path/path
    if target.exists():return schema.model_validate_json(target.read_text(encoding='utf-8')).model_dump()
    value=make();ctx.artifact(path,value);return value

def write_story(ctx,llm,research):
    dossier=research['dossier'];identity=research.get('event_scope',{})
    key=fingerprint({'research':research,'version':2})[:16]
    prefix='editorial/story_v2_'+key
    variants=[]
    strategies=['Paradoxe immediat puis explication','Defi concret puis resolution','Question precise dont la reponse arrive a la fin']
    for i,strategy in enumerate(strategies,1):
        ctx.event('editorial',f'Proposition narrative {i}/3: {strategy}')
        variants.append(cached(ctx,f'{prefix}/variant_{i}.json',Narrative,lambda:llm.ask('writer',
            """Ecris un short FR oral et captivant sur UN evenement. Respecte strictement lieu,
protagonistes et periode de la fiche. Les autres histoires sont exclues. Ni moralite generique,
ni ambiance inventee, ni intentions attribuees sans preuve, ni melange de sommes/objets.
Commence par le paradoxe ou le defi, pas par un decor. Une promesse claire dans les deux
premieres phrases, puis contexte minimal, obstacle, action et revelation. Chaque phrase avance.
Vise 100 a 170 mots si le sujet le permet; aucune obligation de remplir 160 mots.
Decoupe naturellement en 5 a 9 moments narratifs, longueurs variables; un seul sujet par moment.
Le dernier moment doit etre une chute SPECIFIQUE au fait raconte. Numerote 1..N.
Titre accrocheur sans promesse mensongere. Description utile + images de reconstitution.
Utilise uniquement les claim_ids du dossier; pas de citations orales obligatoires.""",
            {'strategie':strategy,'evenement':identity,'dossier':dossier},Narrative,temperature=0.55)))
    valid={i:v for i,v in enumerate(variants,1) if not errors(v,dossier)}
    if not valid:
        # Reparer la structure une fois; les evaluations editoriales restent consultatives.
        fixed=llm.ask('writer','Repare le format, la longueur et les references. Garde un seul evenement. Aucun remplissage.',
            {'draft':variants[0],'errors':errors(variants[0],dossier),'dossier':dossier},Narrative,temperature=0.2)
        if errors(fixed,dossier):raise ReviewNeeded('Aucune narration techniquement exploitable: '+ '; '.join(errors(fixed,dossier)))
        valid={1:fixed}
    choice=cached(ctx,f'{prefix}/selection.json',Selection,lambda:llm.ask('story_selector',
        'Choisis parmi les identifiants proposes le recit le plus coherent puis le plus accrocheur. Penalise fortement tout melange de personnes, pays, epoques ou evenements. Donne au maximum trois corrections precises, realisables avec les faits fournis. Pas de demande de details non documentes. Ce choix ne bloque pas la production.',
        {'evenement':identity,'dossier':dossier,'variants':[{'id':i,'script':v} for i,v in valid.items()]},Selection,temperature=0.1))
    selected=choice['selected'] if choice['selected'] in valid else next(iter(valid))
    draft=valid[selected]
    ctx.event('editorial',f'Proposition {selected} retenue: {choice["reason"]}')
    if choice['corrections']:
        revised=cached(ctx,f'{prefix}/revised.json',Narrative,lambda:llm.ask('writer',
            'Effectue cette UNIQUE revision. Supprime les details etrangers a cet evenement. Applique les corrections sans ajouter de faits; garde accroche, rythme et chute. Ne developpe pas pour remplir une longueur.',
            {'script':draft,'corrections':choice['corrections'],'evenement':identity,'dossier':dossier},Narrative,temperature=0.2))
        if not errors(revised,dossier):draft=revised
        else:ctx.event('editorial','Revision structurellement invalide: conservation de la proposition retenue')
    ctx.artifact(f'{prefix}/selected.json',draft)
    direction=cached(ctx,f'{prefix}/direction.json',Direction,lambda:llm.ask('art_director',
        """Definis EN ANGLAIS une direction visuelle pour CE recit uniquement. L'epoque de l'action
est distincte de l'age de l'objet: une visite de musee en 2019 implique des vetements modernes,
meme devant un coffre ancien. Definis l'objet principal avec forme, couleur et materiau courts,
a reproduire dans tous les plans. Personnages generiques si leur apparence n'est pas documentee.
Style illustration editoriale cinematographique clair, sans effet ancien impose. Evite les objets
contredisant la revelation. Les champs de direction sont courts, maximum 20 mots chacun.""",
        {'evenement':identity,'script':draft},Direction,temperature=0.2))
    bible='; '.join(direction[k] for k in ('action_period','location','main_object','character_appearance','style'))
    scenes=[]
    for scene in draft['scenes']:
        ctx.event('storyboard',f'Plan {scene["id"]}/{len(draft["scenes"])}')
        plan=cached(ctx,f'{prefix}/plan_{scene["id"]}_{fingerprint(draft)[:8]}.json',VisualPlan,lambda:llm.ask('storyboard',
            """Une illustration de CE moment narratif, pas une image generique du theme.
visual en francais, image_prompt en anglais de 45 mots maximum. Place le sujet et l'action
au debut. Reprends mot pour mot les caracteristiques de l'objet lorsqu'il est visible.
Respecte l'epoque de l'ACTION. Varie plan large, gros plan d'objet et detail; sujet principal
au centre pour permettre recadrage. Evite visages ou mains en gros plan si non indispensables.
Ne represente pas la richesse si la revelation dit qu'il n'y en a pas. Pas de texte dans l'image.""",
            {'scene':scene,'script':draft,'direction':direction},VisualPlan,temperature=0.3))
        scenes.append({**scene,**plan})
    script=Script.model_validate({**draft,'visual_bible':bible,'scenes':scenes}).model_dump()
    review={'accepted':True,'assessment_type':'comparative_selection','issues':choice['corrections'],
            'correction':'Selection comparative et revision unique; pas une certification factuelle.'}
    ctx.artifact('editorial/story_summary.json',{'selection':choice,'direction':direction,'words':word_count(script)})
    ctx.event('editorial',f'Recit pret: {word_count(script)} mots, {len(scenes)} moments, revision terminee')
    return {'script':script,'review':review,'selection':choice,'direction':direction}
