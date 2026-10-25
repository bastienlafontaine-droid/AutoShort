"""v0.1.1: narration d'abord, revisions du vrai brouillon, storyboard ensuite."""
import json,hashlib
from pathlib import Path
from uuid import uuid4
from pydantic import Field
from .schemas import Strict,Script,Verdict
from .core import ReviewNeeded

MIN_WORDS=135
MAX_WORDS=190
TARGET_WORDS=160

class NarrationScene(Strict):
    id:int=Field(ge=1,le=12)
    narration:str
    claim_ids:list[str]=Field(min_length=1)

class Narrative(Strict):
    title:str
    description:str
    scenes:list[NarrationScene]=Field(min_length=5,max_length=9)

class BlockingIssue(Strict):
    assertion: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    correction: str = Field(min_length=1)

class ScriptReview(Strict):
    score: int = Field(ge=0,le=10)
    blockers: list[BlockingIssue]
    suggestions: list[str]


class VisualScene(Strict):
    id:int=Field(ge=1,le=12)
    visual:str
    image_prompt:str

class Storyboard(Strict):
    visual_bible:str
    scenes:list[VisualScene]=Field(min_length=5,max_length=9)

class VisualPlan(Strict):
    visual:str
    image_prompt:str

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def accepted_narrative(ctx,research):
    folder=ctx.path/'editorial'
    cache=folder/'accepted_narration.json'
    if cache.exists():
        item=json.loads(cache.read_text(encoding='utf-8'))
        if item.get('research_hash')==fingerprint(research) and not narration_errors(item['narrative'],research['dossier']):
            return item['narrative'],item['review']
    # Recuperation du resultat du correctif 0.1.1 : le couple narration/evaluation a ete sauvegarde.
    source=ctx.path/'research.json'
    candidates=sorted(folder.glob('session_*/review_*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    for path in candidates:
        npath=path.with_name(path.name.replace('review_','narrative_'))
        if not npath.exists() or (source.exists() and source.stat().st_mtime>npath.stat().st_mtime):continue
        try:
            review=Verdict.model_validate_json(path.read_text(encoding='utf-8')).model_dump()
            narrative=Narrative.model_validate_json(npath.read_text(encoding='utf-8')).model_dump()
            if review['accepted'] and review['score']>=ctx.cfg['production']['min_editorial_score'] and not narration_errors(narrative,research['dossier']):
                ctx.artifact('editorial/accepted_narration.json',{'research_hash':fingerprint(research),'narrative':narrative,'review':review})
                return narrative,review
        except (ValueError,OSError):continue
    return None,None

def word_count(script):
    return sum(len(s['narration'].split()) for s in script['scenes'])

def narration_errors(script,dossier):
    errors=[]
    scenes=script['scenes'];ids={x['id'] for x in dossier['claims']}
    if [s['id'] for s in scenes]!=list(range(1,len(scenes)+1)):
        errors.append('Numeroter les scenes de 1 a N sans trous')
    for s in scenes:
        if not s['claim_ids'] or not set(s['claim_ids'])<=ids:
            errors.append(f"Scene {s['id']}: reference a un fait inexistant ou absente")
        if not s['narration'].strip():errors.append(f"Scene {s['id']}: narration vide")
    words=word_count(script)
    if not MIN_WORDS<=words<=MAX_WORDS:
        errors.append(f'La narration contient {words} mots; minimum {MIN_WORDS}, maximum {MAX_WORDS}, cible {TARGET_WORDS}')
    return errors

def script_errors(script,dossier):
    errors=narration_errors(script,dossier)
    for s in script['scenes']:
        if not s['image_prompt'].strip():errors.append(f"Scene {s['id']}: prompt image vide")
    return errors

def previous_draft(ctx,dossier):
    """Reutilise un brouillon de ce run uniquement, y compris ceux de v0.1."""
    folder=getattr(ctx,'path',None)
    if folder is None:return None
    candidates=[]
    for pattern in ('script_*.json','session_*/narrative_*.json'):
        for path in (folder/'editorial').glob(pattern):
            try:
                value=json.loads(path.read_text(encoding='utf-8-sig'))
                raw={'title':value['title'],'description':value['description'],
                     'scenes':[{k:s[k] for k in ('id','narration','claim_ids')} for s in value['scenes']]}
                draft=Narrative.model_validate(raw).model_dump()
                # On ne reutilise pas un brouillon avec des references devenues invalides.
                valid_ids={c['id'] for c in dossier['claims']}
                if all(set(s['claim_ids'])<=valid_ids for s in draft['scenes']):
                    candidates.append((-path.stat().st_mtime,abs(word_count(draft)-TARGET_WORDS),draft))
            except (ValueError,KeyError,TypeError,OSError):continue
    if not candidates:return None
    return min(candidates,key=lambda x:(x[0],x[1]))[2]

def diagnostics(ctx,prefix,attempt,script,errors,review=None):
    value={'phase':'narration','attempt':attempt+1,'words':word_count(script),
           'target_words':TARGET_WORDS,'minimum_words':MIN_WORDS,'maximum_words':MAX_WORDS,
           'scene_words':[{'id':s['id'],'words':len(s['narration'].split())} for s in script['scenes']],
           'errors':errors,'review':review}
    ctx.artifact(f'{prefix}/validation_{attempt}.json',value)
    ctx.artifact('editorial/last_validation.json',value)
    message=f"Narration {attempt+1}: {value['words']} mots"
    if errors:message+=' — '+'; '.join(errors)
    elif review:message+=f" — juge {review['score']}/10, accepte={review['accepted']}"
    ctx.event('editorial',message)

def write_script(ctx,llm,research,narrative_only=False):
    if ctx.cfg['production'].get('story_pipeline',1)>=2:
        from .storytelling import write_story
        return write_story(ctx,llm,research,narrative_only=narrative_only)
    dossier=research['dossier']
    draft=previous_draft(ctx,dossier)
    prefix='editorial/session_'+uuid4().hex[:10]
    feedback=narration_errors(draft,dossier) if draft else []
    last=ctx.path/'editorial/last_validation.json'
    if draft and last.exists():
        try:
            old=json.loads(last.read_text(encoding='utf-8')).get('review') or {}
            feedback+=old.get('issues',[])+([old['correction']] if old.get('correction') else [])
        except (ValueError,OSError):pass
    polished=False
    exhausted_review=None
    if draft and last.exists() and not narration_errors(draft,dossier):
        try:
            prior=json.loads(last.read_text(encoding='utf-8'))
            research_file=ctx.path/'research.json'
            unchanged=not research_file.exists() or research_file.stat().st_mtime<=last.stat().st_mtime
            if unchanged and prior.get('attempt',0)>=ctx.cfg['production']['script_attempts'] and prior.get('words')==word_count(draft) and prior.get('review') and not prior.get('errors'):
                exhausted_review=prior['review']
        except (ValueError,OSError):pass
    if draft:ctx.event('editorial',f'Revision du brouillon precedent ({word_count(draft)} mots)')
    accepted,review=accepted_narrative(ctx,research)
    if accepted is None and exhausted_review is not None:
        accepted=draft;review=exhausted_review
        ctx.event('editorial','Corrections deja effectuees: poursuite avec reserves conservees dans le rapport')
    if accepted:ctx.event('editorial',f"Reprise de la narration sauvegardee ({word_count(accepted)} mots)")
    attempts=ctx.cfg['production']['script_attempts']
    for attempt in range(0 if accepted else attempts):
        count=word_count(draft) if draft else 0
        request={'dossier_verifie':dossier,'previous_draft':draft,'feedback':feedback,
          'length':{'current_words':count,'minimum_words':MIN_WORDS,'maximum_words':MAX_WORDS,
                    'target_words':TARGET_WORDS,'suggested_scenes':7,'words_per_scene':'22 a 25',
                    'words_to_add_to_target':max(0,TARGET_WORDS-count)},
          'counting_rule':'Seuls les mots des champs narration comptent, separes par espaces; titres, descriptions et visuels exclus.'}
        draft=llm.ask('writer',
          '''Ecris UNIQUEMENT la narration en francais. Ne produis ni image_prompt ni storyboard.
Objectif concret: 7 scenes de 22 a 25 mots chacune, environ 160 mots de narration au total.
Le minimum obligatoire est 135 mots; le maximum est 190. Titres et description ne comptent pas.
Si previous_draft est fourni, REVISE ce texte precis selon les erreurs et le nombre de mots manquants.
Ne te contente pas de changer des synonymes. Developpe les faits pertinents disponibles dans le dossier,
avec une accroche immediate, un contexte clair, une progression et une chute memorable.
Priorite a la curiosite et a la retention : revele le paradoxe des la premiere phrase,
garde la resolution pour la fin, phrases courtes et orales. Un titre intrigant est souhaite.
Raconte UN SEUL evenement. Ne melange jamais le contenu, les sommes ou les personnages de plusieurs coffres ou anecdotes. Si un fait du dossier semble concerner une autre affaire, omets-le.
Un short n'est pas un article exhaustif. Les suggestions du juge ne sont pas de nouvelles sources.
Si un detail demande n'est pas documente, OMETS-LE ou formule prudemment ce qui est etabli.
Ne promets pas dans le titre ou l'accroche une revelation absente de la narration.
N'ajoute aucun fait, chiffre, dialogue, sentiment ou lien de causalite non soutenu par le dossier.
N'invente pas de remplissage pour atteindre la longueur; ne repete pas la meme conclusion.
Chaque scene reference tous les claim_ids necessaires. Numerotation 1..N sans trous.
Ecris une vraie description de la video, jamais une description de la consigne.
La description doit indiquer que les images sont des reconstitutions illustrees.
Le schema doit etre respecte. Retourne le texte revise complet, pas un commentaire.''',
          request,Narrative,temperature=0.4)
        ctx.artifact(f'{prefix}/narrative_{attempt}.json',draft)
        errors=narration_errors(draft,dossier)
        if errors:
            diagnostics(ctx,prefix,attempt,draft,errors)
            feedback=errors;continue
        assessment=llm.ask('script_judge',
          """Evalue un short narratif accrocheur, pas un article encyclopedique.
Separe blockers (erreurs materielles) et suggestions (ameliorations facultatives).
Un blocker doit citer une affirmation effectivement presente dans le script et expliquer
une contradiction avec le dossier, une invention centrale ou une promesse trompeuse.
Correction obligatoire: donne une reformulation appuyee par le dossier ou demande de retirer
l'affirmation. Ne demande jamais au redacteur de chercher ou d'inventer un detail absent.
Ne bloque PAS pour manque d'exhaustivite, detail secondaire non precise, absence de citation
orale, nuance deja omise ou question ouverte sans affirmation trompeuse dans le texte.
Exemple: ne pas detailler des documents dans un coffre n'est pas un blocker. Affirmer que
ces documents sont secrets sans preuve peut en etre un. Affirmer qu'un code etait aleatoire
sans preuve: retirer le mot aleatoire suffit, ne pas exiger d'etablir l'origine du code.
score concerne uniquement accroche, clarte, rythme et chute. Il est indicatif.
Les suggestions doivent etre courtes et applicables aux faits disponibles. Pas de prediction des vues.
Le storyboard sera produit ensuite.""",{'script':draft,'research':research},ScriptReview,temperature=0.1)
        ctx.artifact(f'{prefix}/assessment_{attempt}.json',assessment)
        blocking=[x['assertion']+': '+x['reason']+' Correction: '+x['correction'] for x in assessment['blockers']]
        review={'accepted':not blocking,'score':assessment['score'],
                'issues':blocking+assessment['suggestions'],
                'correction':' ; '.join(x['correction'] for x in assessment['blockers'])}
        ctx.artifact(f'{prefix}/review_{attempt}.json',review)
        diagnostics(ctx,prefix,attempt,draft,[],review)
        if blocking:
            feedback=blocking
            ctx.event('editorial',f'{len(blocking)} erreur(s) materielle(s): correction automatique')
            continue
        # Une seule passe de polissage facultatif; jamais de boucle pour des details secondaires.
        if assessment['suggestions'] and not polished and attempt+1<attempts:
            polished=True;feedback=assessment['suggestions']
            ctx.event('editorial','Suggestions non bloquantes: une passe de polissage automatique')
            continue
        accepted=draft
        if assessment['suggestions']:
            ctx.event('editorial','Suite du montage: suggestions restantes non bloquantes')
        break
    if accepted is None:
        structural=narration_errors(draft,dossier) if draft else ['Aucune narration exploitable']
        if structural:
            raise ReviewNeeded('Narration inexploitable techniquement: '+'; '.join(structural))
        accepted=draft
        # Le verdict reste honnete : le passage a la suite ne signifie pas validation factuelle.
        review=review or {'accepted':False,'score':0,'issues':feedback,'correction':''}
        ctx.event('editorial','Limite des corrections atteinte: poursuite automatique avec reserves')
    if not review.get('accepted',False):
        ctx.artifact('editorial/reservations.json',{'policy':'continue_after_revisions','review':review})
    ctx.artifact('editorial/accepted_narration.json',{'research_hash':fingerprint(research),'narrative':accepted,'review':review})
    payload={'narrative':accepted,'review':review,'prefix':prefix}
    if narrative_only:return payload
    return build_storyboard(ctx,llm,research,payload)

def build_storyboard(ctx,llm,research,payload):
    if 'choice' in payload:
        from .storytelling import story_board
        return story_board(ctx,llm,research,payload)
    accepted=payload['narrative'];review=payload['review'];prefix=payload['prefix']
    dossier=research['dossier']
    # Une demande courte par scene : aucun tableau, id ou narration a regenerer par le modele.
    key=fingerprint(accepted)
    plans=[]
    bible='Historical editorial illustration, painterly cinematic composition, warm muted colors, period-appropriate clothing and objects, no readable text'
    for scene in accepted['scenes']:
        rel=f"editorial/visual_plans/{key[:16]}_{scene['id']:02d}.json"
        cache=ctx.path/rel
        if cache.exists():
            plan=VisualPlan.model_validate_json(cache.read_text(encoding='utf-8')).model_dump()
            ctx.event('storyboard',f"Scene {scene['id']}: reprise du plan valide")
        else:
            ctx.event('storyboard',f"Scene {scene['id']}/{len(accepted['scenes'])}: creation du plan visuel")
            plan=llm.ask('storyboard',
              "Decris UNE SEULE illustration pour la scene fournie. Reponds exactement avec deux champs: visual (description francaise) et image_prompt (prompt anglais, 40 mots maximum). Aucun id, aucune liste scenes, aucune narration. Composition simple, epoque et objets coherents avec les faits. Evite visages historiques precis et uniformes inventes. Pas de texte lisible ni inscription exacte.",
              {'scene':scene,'verified_facts':[c for c in dossier['claims'] if c['id'] in scene['claim_ids']],
               'title':accepted['title'],'visual_style':bible},VisualPlan,temperature=0.3)
            if not plan['visual'].strip() or not plan['image_prompt'].strip():
                raise ReviewNeeded(f"Storyboard scene {scene['id']}: description ou prompt vide")
            ctx.artifact(rel,plan)
        plans.append(plan)
    script={**accepted,'visual_bible':bible,'scenes':[{**scene,**plan} for scene,plan in zip(accepted['scenes'],plans)]}
    script=Script.model_validate(script).model_dump()
    ctx.artifact(f'{prefix}/script_accepted.json',script)
    ctx.event('editorial',f"Script pret pour montage: {word_count(script)} mots; storyboard termine")
    return {'script':script,'review':review}
