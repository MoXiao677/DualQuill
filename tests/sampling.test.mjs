import {test} from 'node:test';
import assert from 'node:assert/strict';
import {samplingDraft,samplingOptions,captureSampling,fillSampling,renderSampling} from '../src/novel_writer/ui/static/sampling.js';

test('native preset fields survive rendered editing and raw draft conversion',()=>{
 const native={top_p:null,seed:null,stop:[],temperature_mode:'omit',chat_token_field:'max_completion_tokens'};
 assert.deepEqual(samplingOptions(samplingDraft(native)),{sampling:native});
 const note={textContent:''},controls=Object.fromEntries(['top-p','seed','stop'].map(k=>['[data-sampling-'+k+']',{value:''}]));
 const box={dataset:{},querySelector:()=>note},root={matches:()=>false,querySelector:s=>s==='[data-sampling]'?box:controls[s]};
 fillSampling(root,native);assert.deepEqual(samplingOptions(captureSampling(root)),{sampling:native});assert.match(note.textContent,/max_completion_tokens/);assert.match(renderSampling('native',native),/data-native-profile/);
 fillSampling(root,undefined);assert.deepEqual(samplingOptions(captureSampling(root)),{});
});

test('omitting temperature retains explicitly chosen extra sampling values',()=>{
 assert.deepEqual(samplingOptions({temperature_mode:'omit',top_p:'.999',seed:'17',stop:'END'}),{sampling:{temperature_mode:'omit',top_p:.999,seed:17,stop:['END']}});
});
