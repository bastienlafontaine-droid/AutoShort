"""v0.1.1: narration d'abord, revisions du vrai brouillon, storyboard ensuite."""
import json
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

class VisualScene(Strict):
    id:int=Field(ge=1,le=12)
    visual:str
    image_prompt:str

class Storyboard(Strict):
    visual_bible:str
    scenes:list[VisualScene]=Field(min_length=5,max_length=9)

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
                    candidates.append((abs(word_count(draft)-TARGET_WORDS),-path.stat().st_mtime,draft))
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

def write_script(ctx,llm,research):
    dossier=research['dossier']
    draft=previous_draft(ctx,dossier)
    prefix='editorial/session_'+uuid4().hex[:10]
    feedback=narration_errors(draft,dossier) if draft else []
    if draft:ctx.event('editorial',f'Revision du brouillon precedent ({word_count(draft)} mots)')
    accepted=None;review=None
    attempts=ctx.cfg['production']['script_attempts']
    for attempt in range(attempts):
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
avec une accroche, un contexte clair, une progression chronologique et un denouement.
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
        review=llm.ask('script_judge',
          '''Verifie chaque affirmation de cette narration par rapport aux faits et sources.
Refuse causalite, nombre, chronologie ou detail invente, meme si les claim_ids existent.
Puis evalue clarte orale, accroche, progression, chute et absence de remplissage.
accepted=false s'il existe un probleme factuel, meme avec score eleve. Donne des corrections concretes.
Le storyboard sera produit ensuite: ne juge ni son absence, ni la langue de prompts inexistants.
Aucune prediction des vues.''',{'script':draft,'research':research},Verdict,temperature=0.1)
        ctx.artifact(f'{prefix}/review_{attempt}.json',review)
        diagnostics(ctx,prefix,attempt,draft,[],review)
        if review['accepted'] and review['score']>=ctx.cfg['production']['min_editorial_score']:
            accepted=draft;break
        feedback=review['issues']+[review['correction']]
        if review['score']<ctx.cfg['production']['min_editorial_score']:
            feedback.append(f"Score editorial {review['score']}/10 inferieur au seuil {ctx.cfg['production']['min_editorial_score']}")
    if accepted is None:
        count=word_count(draft) if draft else 0
        reason='; '.join(feedback) or 'Le juge editorial a refuse le script'
        raise ReviewNeeded(f'Script non valide: derniere narration {count} mots. {reason}. Details: editorial/last_validation.json')
    # La narration validee est immuable. Le storyboard ne peut pas la reecrire.
    feedback=[]
    for attempt in range(2):
        board=llm.ask('storyboard',
          '''Produis uniquement le storyboard de la narration validee. Ne modifie pas la narration.
Retourne exactement une scene visuelle par scene du script avec les memes ids dans le meme ordre.
visual est en francais, image_prompt EN ANGLAIS (maximum 40 mots), visual_bible EN ANGLAIS.
Une composition simple et lisible par image, costumes/lieux coherents avec le dossier.
Privilegie objets et lieux; evite d'inventer un uniforme d'archeologue ou un visage historique precis.
Pas de texte lisible ni de reconstitution d'inscription exacte dans l'image.
Les images illustrent le recit, ce ne sont pas des preuves documentaires. Applique le feedback fourni.''',
          {'narration':accepted,'dossier':dossier,'feedback':feedback},Storyboard,temperature=0.3)
        ctx.artifact(f'{prefix}/storyboard_{attempt}.json',board)
        expected=[s['id'] for s in accepted['scenes']]
        if [s['id'] for s in board['scenes']]!=expected:
            feedback=['Les ids du storyboard doivent etre exactement '+str(expected)]
        elif not board['visual_bible'].strip() or any(not s['image_prompt'].strip() or not s['visual'].strip() for s in board['scenes']):
            feedback=['Les descriptions et prompts ne doivent pas etre vides']
        else:
            script={**accepted,'visual_bible':board['visual_bible'],
                    'scenes':[{**s,'visual':v['visual'],'image_prompt':v['image_prompt']} for s,v in zip(accepted['scenes'],board['scenes'])]}
            script=Script.model_validate(script).model_dump()
            ctx.artifact(f'{prefix}/script_accepted.json',script)
            ctx.event('editorial',f"Script accepte: {word_count(script)} mots; storyboard termine")
            return {'script':script,'review':review}
        ctx.artifact(f'{prefix}/storyboard_errors_{attempt}.json',feedback)
    raise ReviewNeeded('Narration validee, mais storyboard non valide: '+'; '.join(feedback))
