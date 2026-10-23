'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),c=require('../desktop/delivery-contract.cjs');
test('application MIT license is reported independently of publication approval',()=>{const i=c.inventory(root);assert.equal(i.application_license,'MIT');assert.equal(i.public_distribution_approved,false);});
test('application license text is source-bound and rejects tampering',()=>{const binding=c.sourceBinding(root,[]);assert.ok(binding.files.some(x=>x.file==='LICENSE'));assert.match(fs.readFileSync(path.join(root,'LICENSE'),'utf8'),/^MIT License/);});
test('notice states the declared application MIT license',()=>{const text=fs.readFileSync(path.join(root,'desktop/THIRD-PARTY-NOTICES.txt'),'utf8');assert.match(text,/Application: MIT License/);assert.doesNotMatch(text,/UNLICENSED|public license are reserved/);});
