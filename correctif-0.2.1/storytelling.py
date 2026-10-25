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
    v3=ctx.cfg['production'].get('story_pipeline',2)>=3
    language=ctx.cfg['production'].get('language','fr')
    language_rule=' Write all narration, titles and descriptions in natural spoken American English. Explain unfamiliar local acronyms briefly. No generic moral or abstract closing commentary.' if language=='en' else ' Ecris la narration en francais.'
    key=fingerprint({'research':research,'version':3 if v3 else 2,'language':language})[:16]
    prefix='editorial/story_v2_'+key
    variants=[]
    strategies=['Paradoxe immediat puis explication','Defi concret puis resolution','Question precise dont la reponse arrive a la fin']
    for i,strategy in enumerate(strategies,1):
        ctx.event('editorial',f'Proposition narrative {i}/3: {strategy}')
        variants.append(cached(ctx,f'{prefix}/variant_{i}.json',Narrative,lambda:llm.ask('writer',
            """Ecris un short oral et captivant sur UN evenement. Respecte strictement lieu,
protagonistes et periode de la fiche. Les autres histoires sont exclues. Ni moralite generique,
ni ambiance inventee, ni intentions attribuees sans preuve, ni melange de sommes/objets.
Commence par le paradoxe ou le defi, pas par un decor. Une promesse claire dans les deux
premieres phrases, puis contexte minimal, obstacle, action et revelation. Chaque phrase avance.
Vise 100 a 170 mots si le sujet le permet; aucune obligation de remplir 160 mots.
Decoupe naturellement en 5 a 9 moments narratifs, longueurs variables; un seul sujet par moment.
Le dernier moment doit etre une chute SPECIFIQUE au fait raconte. Numerote 1..N.
Titre accrocheur sans promesse mensongere. Description utile + images de reconstitution.
Utilise uniquement les claim_ids du dossier; pas de citations orales obligatoires."""+language_rule,
            {'strategie':strategy,'evenement':identity,'dossier':dossier},Narrative,temperature=0.55)))
    valid={i:v for i,v in enumerate(variants,1) if not errors(v,dossier)}
    if not valid:
        # Reparer la structure une fois; les evaluations editoriales restent consultatives.
        fixed=llm.ask('writer','Repare le format, la longueur et les references. Garde un seul evenement. Aucun remplissage.'+language_rule,
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
            'Effectue cette UNIQUE revision. Supprime les details etrangers a cet evenement. Applique les corrections sans ajouter de faits; garde accroche, rythme et chute. Ne developpe pas pour remplir une longueur.'+language_rule,
            {'script':draft,'corrections':choice['corrections'],'evenement':identity,'dossier':dossier},Narrative,temperature=0.2))
        if not errors(revised,dossier):draft=revised
        else:ctx.event('editorial','Revision structurellement invalide: conservation de la proposition retenue')
    ctx.artifact(f'{prefix}/selected.json',draft)
    direction=cached(ctx,f'{prefix}/direction.json',Direction,lambda:llm.ask('art_director',
        """Definis EN ANGLAIS une direction visuelle pour CE recit uniquement. L'epoque de l'action
est distincte de l'age de l'objet: une visite de musee en 2019 implique des vetements modernes,
meme devant un coffre ancien. Definis l'objet principal avec forme, couleur et materiau courts,
a reproduire UNIQUEMENT lorsqu’il est necessaire a la scene. Ne force jamais cet objet ou ce lieu dans tous les plans. Personnages generiques si leur apparence n'est pas documentee.
Style illustration editoriale cinematographique clair, sans effet ancien impose. Evite les objets
contredisant la revelation. Les champs de direction sont courts, maximum 20 mots chacun.""",
        {'evenement':identity,'script':draft},Direction,temperature=0.2))
    bible=direction['style'] if v3 else '; '.join(direction[k] for k in ('action_period','location','main_object','character_appearance','style'))
    scenes=[]
    for scene in draft['scenes']:
        ctx.event('storyboard',f'Plan {scene["id"]}/{len(draft["scenes"])}')
        plan=cached(ctx,f'{prefix}/plan_{scene["id"]}_{fingerprint(draft)[:8]}.json',VisualPlan,lambda:llm.ask('storyboard',
            """Une illustration de CE moment narratif, pas une image generique du theme.
visual et image_prompt en anglais de 45 mots maximum. Place le sujet et l'action
au debut. Reprends mot pour mot les caracteristiques de l'objet lorsqu'il est visible.
Respecte l'epoque de l'ACTION. Varie plan large, gros plan d'objet et detail; sujet principal
au centre pour permettre recadrage. Evite visages ou mains en gros plan si non indispensables.
Ne represente pas la richesse si la revelation dit qu'il n'y en a pas. Pas de texte dans l'image.
Un seul cadre, jamais collage ni cases multiples. Choisis lieu, personnages et objets pour CETTE
phrase uniquement: la direction est une reference conditionnelle, pas une liste a inclure.
Une reaction exige une action/attitude visible, pas le decor initial. Si abstrait, utilise une
metaphore visuelle clairement illustrative sans inventer une scene historique precise.""",
            {'scene':scene,'script':draft,'direction':direction},VisualPlan,temperature=0.3))
        scenes.append({**scene,**plan})
    if v3:scenes=review_board(ctx,llm,prefix,scenes,direction)
    script=Script.model_validate({**draft,'visual_bible':bible,'scenes':scenes}).model_dump()
    review={'accepted':True,'assessment_type':'comparative_selection','issues':choice['corrections'],
            'correction':'Selection comparative et revision unique; pas une certification factuelle.'}
    ctx.artifact('editorial/story_summary.json',{'selection':choice,'direction':direction,'words':word_count(script)})
    ctx.event('editorial',f'Recit pret: {word_count(script)} mots, {len(scenes)} moments, revision terminee')
    return {'script':script,'review':review,'selection':choice,'direction':direction}


class PlanIssue(Strict):
    scene_id: int
    reason: str
    correction: str

class BoardReview(Strict):
    accepted: bool
    issues: list[PlanIssue]


def review_board(ctx,llm,prefix,scenes,direction):
    """Review the sequence, repair only failed shots; cache every pass for resume."""
    scenes=[dict(s) for s in scenes]
    for attempt in range(3):
        key=fingerprint(scenes)[:12]
        ctx.event('storyboard',f'Controle progression visuelle {attempt+1}/3')
        verdict=cached(ctx,f'{prefix}/board_review_{attempt}_{key}.json',BoardReview,lambda:llm.ask(
            'storyboard_judge',
            """Strictly judge the complete storyboard against each scene's narration.
Reject repeated generic setting/action when the narrative has moved to reactions or consequences.
Changing camera angle alone is not narrative progression. Allow the same object when needed.
Reject collages, unsupported events, contradictory roles/eras, and plans that cannot show the narrated beat.
Return scene-specific issues only for material problems, with a concrete replacement direction.
Do not request invented historical details. accepted=true only when issues is empty.""",
            {'scenes':scenes,'conditional_reference':direction},BoardReview,temperature=0.1))
        if verdict['accepted'] and not verdict['issues']:return scenes
        if attempt==2:
            raise ReviewNeeded('Storyboard encore incoherent apres 2 corrections automatiques. Details: '+prefix)
        ids={s['id'] for s in scenes}
        issues={i['scene_id']:i for i in verdict['issues'] if i['scene_id'] in ids}
        if not issues:issues={s['id']:{'correction':'Show this specific narrative beat in one clear frame; avoid generic repetition.'} for s in scenes}
        for scene in scenes:
            if scene['id'] not in issues:continue
            plan=cached(ctx,f"{prefix}/board_repair_{attempt}_{key}_{scene['id']}.json",VisualPlan,lambda:llm.ask(
                'storyboard',
                'Replace this visual plan. English only. One frame, no collage. image_prompt maximum 45 words, subject and visible action first. Include only scene-relevant objects and people. Avoid unsupported literal reenactments.',
                {'scene':scene,'feedback':issues[scene['id']],'other_scenes':scenes,'conditional_reference':direction},VisualPlan,temperature=0.2))
            scene.update(plan)
    return scenes
