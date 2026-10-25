import re
from difflib import SequenceMatcher
from .core import normalize

def spoken(text,language="fr"):
    from num2words import num2words
    text=re.sub(r'\b\d+\b',lambda m:num2words(int(m.group()),lang=language),text)
    return text

def tokens(text,language="fr"): return normalize(spoken(text,language)).split()

def word_error(expected,actual,language="fr"):
    a,b=tokens(expected,language),tokens(actual,language)
    if not a:return 1.0
    prev=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        row=[i]
        for j,y in enumerate(b,1): row.append(min(row[-1]+1,prev[j]+1,prev[j-1]+(x!=y)))
        prev=row
    return prev[-1]/len(a)

def captions(narration,words,duration,offset=0.0):
    """Texte original, temps ASR quand correspondance; interpolation explicite sinon."""
    original=narration.split(); source=[normalize(x) for x in original]
    heard=[normalize(w['word']) for w in words]
    mapping={}
    for block in SequenceMatcher(None,source,heard,autojunk=False).get_matching_blocks():
        for k in range(block.size):mapping[block.a+k]=block.b+k
    coverage=len(mapping)/max(1,len(original)); items=[]
    # Groupes lisibles, limites en caracteres; priorite aux ponctuations.
    groups=[];start=0
    dangling={'the','a','an','of','to','and','with','in','for','de','du','des','le','la','les','un','une','a','à','et','en','au','aux','son','sa','ses','pour','avec'}
    while start<len(original):
        end=start
        while end<len(original) and end-start<5:
            candidate=' '.join(original[start:end+1])
            if end>start and len(candidate)>32:break
            end+=1
            if original[end-1].endswith(('.',',',';',':','!','?')):break
        if end-start>2 and original[end-1].lower() in dangling:end-=1
        groups.append((start,end));start=end
    for start,end in groups:
        if start in mapping and end-1 in mapping:
            t0=words[mapping[start]]['start'];t1=words[mapping[end-1]]['end']
        else:t0=duration*start/len(original);t1=duration*end/len(original)
        t0=max(items[-1]['end']-offset if items else 0,min(t0,duration-0.01))
        t1=max(t0+0.01,min(t1,duration))
        if t0>=duration:continue
        items.append({'start':offset+t0,'end':offset+min(t1,duration),'text':' '.join(original[start:end])})
    return items,coverage
