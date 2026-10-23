"""Deterministic Unicode lexical ranking. No embeddings, network, or model calls."""
from collections import Counter
import math
import re
import unicodedata
from typing import Protocol


class RankingBackend(Protocol):
    """Internal extension contract; no backend can be enabled by HTTP options.

    A future embedding backend must separately implement consent, request budget,
    transport and measured quality before claiming semantic capability. Callers
    must still validate each returned source version and excerpt themselves.
    """
    semantic:bool
    def rank(self,query:str,documents:list[dict])->list[dict]:...


def _joins(text,start,index):
    following=unicodedata.normalize('NFKC',text[index])
    if unicodedata.combining(text[index]) or unicodedata.combining(following[0]):return True
    cp=ord(following[0])
    if 0x1160<=cp<=0x11ff or 0xd7b0<=cp<=0xd7fb:
        previous=ord(unicodedata.normalize('NFKC',text[start:index])[-1])
        if 0x1160<=cp<=0x11a7 or 0xd7b0<=cp<=0xd7c6:return 0x1100<=previous<=0x115f or 0xa960<=previous<=0xa97f
        return (0xac00<=previous<=0xd7a3 and (previous-0xac00)%28==0) or 0x1160<=previous<=0x11a7
    return False


def normalized_spans(text):
    """NFKC/casefold with offsets into the original Unicode code-point string."""
    pieces=[];spans=[];start=0
    for index in range(1,len(text)+1):
        if index<len(text) and _joins(text,start,index):continue
        value=unicodedata.normalize('NFKC',text[start:index]).casefold()
        pieces.append(value);spans.extend([(start,index)]*len(value));start=index
    return ''.join(pieces),spans


def terms(text):
    """Words plus overlapping CJK bigrams; explicitly lexical, not semantic."""
    result=[]
    han=r'\u3400-\u9fff\U00020000-\U000323af'
    for match in re.finditer('['+han+']+|(?:(?!['+han+'])[^\\W_])+',text,re.UNICODE):
        word=match.group()
        if '\u3400'<=word[0]<='\u9fff' or '\U00020000'<=word[0]<='\U000323af':
            result.extend((word[i:i+2],match.start()+i,match.start()+min(len(word),i+2)) for i in range(max(1,len(word)-1)))
        else:result.append((word,match.start(),match.end()))
    return result


def rank(query,documents):
    """Fuse phrase and BM25 rankings, then rerank by matched query coverage.

    Each document has a text and caller-owned metadata. Evidence always points
    into that exact original text. Empty/no-overlap queries never invent hits.
    """
    normalized_query,_=normalized_spans(query);wanted=Counter(t[0] for t in terms(normalized_query))
    if not normalized_query.strip():return []
    prepared=[];df=Counter();total_tokens=0
    for ordinal,document in enumerate(documents):
        normalized,spans=normalized_spans(document['text']);tokens=terms(normalized);counts=Counter(t[0] for t in tokens)
        matched=set(wanted)&counts.keys();phrase=normalized.find(normalized_query)
        df.update(matched);total_tokens+=len(tokens)
        if not matched and phrase<0:continue
        evidence=[(start,end) for term,start,end in tokens if term in matched]
        a,b=(phrase,phrase+len(normalized_query)) if phrase>=0 else min(evidence,key=lambda pair:pair[0])
        start,end=spans[a][0],spans[min(b,len(spans))-1][1]
        # Keep only query-term projections, never a corpus-wide per-character
        # offset/token cache. Normalization maps live for one window at a time.
        prepared.append(dict(document=document,ordinal=ordinal,counts={t:counts[t] for t in matched},length=len(tokens),phrase=phrase>=0,
            coverage=1 if phrase>=0 else len(matched)/max(1,len(wanted)),matched_terms=sorted(matched),start=start,end=end))
    average=total_tokens/max(1,len(documents));candidates=prepared
    for value in candidates:
        value['bm25']=sum(math.log(1+(len(documents)-df[t]+.5)/(df[t]+.5))*count*2.2/(count+1.2*(.25+.75*value['length']/max(1,average))) for t,count in value['counts'].items())
    bm25=sorted(candidates,key=lambda v:(-v['bm25'],v['ordinal']))
    phrase=sorted((c for c in candidates if c['phrase']),key=lambda v:v['ordinal'])
    fusion={v['ordinal']:1/(60+i+1) for i,v in enumerate(bm25)}
    for i,value in enumerate(phrase):fusion[value['ordinal']]+=1/(60+i+1)
    for value in candidates:
        value['score']=fusion[value['ordinal']]+value['coverage']*.05
        value['explanation']=dict(method='unicode_lexical_bm25_phrase_rrf_v1',bm25=round(value['bm25'],8),phrase=value['phrase'],coverage=value['coverage'],matched_terms=value['matched_terms'],semantic=False)
    return sorted(candidates,key=lambda v:(-v['score'],v['ordinal']))


class LexicalBackend:
    semantic=False
    rank=staticmethod(rank)
