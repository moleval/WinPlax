#!/usr/bin/env node
// РЕАЛЬНЫЙ прогон ОК-1 на open-pdf-studio frame element (js/gevelelement)
// Использует реальные модули catalogus.js + indeling.js + weergave.js
// Запуск: node real_open_pdf_studio_ok1.mjs

import { indeling, voegStijlToe, verdeelGelijk } from './repos/open-pdf-studio/open-pdf-studio/js/gevelelement/indeling.js';
import { preset, stijlType } from './repos/open-pdf-studio/open-pdf-studio/js/gevelelement/catalogus.js';
import { tekenOpdrachten } from './repos/open-pdf-studio/open-pdf-studio/js/gevelelement/weergave.js';

const OUT = 'real_output';
import fs from 'fs';
import path from 'path';

// ОК-1: проём 1500×1500 шов 30 → окно 1440×1440, 3×2
// В frame element длина = OverallWidth = 1440 (в плане вдоль стены)
// Но frame element — 1D вдоль стены: длина 1440, высота задаётся отдельно (в WinPlax 1440)
// Для 3×2 нужен 2D — в open-pdf-studio 2D нет, только 1D деление по длине.
// Демо: покажем 1D деление 1440 на 3 поля (вертикальные импосты), и отдельно 1D деление высоты 1440 на 2 поля (горизонтальный импост)
// Это ограничение: frame element 1D, WinPlax 2D (cols×rows)

function printIndeling(name, params, presetId) {
  const lay = indeling(params, presetId);
  console.log(`\n=== ${name} preset=${presetId} ===`);
  console.log(`  lengte ${lay.lengteMm} diepte ${lay.diepteMm} expliciet=${lay.expliciet}`);
  console.log(`  stijlen (${lay.stijlen.length}):`);
  lay.stijlen.forEach(s => console.log(`    [${s.index}] ${s.rol} pos=${s.posMm} type=${s.type} b=${s.breedteMm} d=${s.diepteMm} van=${s.vanMm} tot=${s.totMm}`));
  console.log(`  velden (${lay.velden.length}):`);
  lay.velden.forEach(v => console.log(`    [${v.index}] van=${v.vanMm} tot=${v.totMm} breedte=${v.breedteMm} dag=${v.dagMm} paneel=${JSON.stringify(v.paneel)}`));
  // Текстовые команды для DXF-подобного просмотра
  // const bbox={x:0,y:0,width:1440,height:114}
  // const cmds=tekenOpdrachten(params, presetId, bbox);
  // console.log(`  weergave cmds ${cmds.length}`);
  return lay;
}

// 1. ОК-1 как vliesgevel 1440 длина, 3 поля (вертикальные импосты)
// Автоматически: 3600/1200=3 поля, но для 1440 должно быть 1-2 поля, поэтому задаём явно
let p1 = {
  lengte: 1440,
  stijlen: [{pos: 480, type: 'alu-50x150'}, {pos: 960, type: 'alu-50x150'}], // 1440/3=480
  kader: ['alu-50x150','alu-50x150'],
  panelen: [{type:'glas'},{type:'glas'},{type:'glas'}],
  binnenzijde: 'rechts'
};
printIndeling("OK-1 ВЕРТИКАЛЬ 3 поля (vliesgevel 1440, 2 импоста)", p1, 'vliesgevel');

// Для сравнения: тот же размер как kozijn 67×114
let p1k = {
  lengte: 1440,
  stijlen: [{pos: 480, type: 'hout-67x114'}, {pos: 960, type: 'hout-67x114'}],
  kader: ['hout-67x114','hout-67x114'],
  panelen: [{type:'glas'},{type:'glas'},{type:'glas'}],
};
printIndeling("OK-1 ВЕРТИКАЛЬ 3 поля (kozijn 67×114)", p1k, 'kozijn');

// 2. ОК-1 горизонтальное деление 1440 на 2 поля (высота)
let p2 = {
  lengte: 1440,
  stijlen: [{pos: 720, type: 'alu-50x150'}],
  kader: ['alu-50x150','alu-50x150'],
  panelen: [{type:'glas'},{type:'glas'}],
};
printIndeling("OK-1 ГОРИЗОНТАЛЬ 2 поля (высота 1440, 1 импост)", p2, 'vliesgevel');

// 3. Индивидуальные ширины как в WinPlax: cell_w 386.6, но в frame element dagMm = veld breedte - stijl breedte
// Для vliesgevel 50×150: 2 импоста по 50 → свободные поля dag = 480-50 =430? Не 386!
// Проверим: lay1 dagMm для 1440/3 с 50mm stijl: первый dag = 480-25-25? Wait kader 50, tussen 50
// В indeling: b0=25? Actually kader 50 → b0=50, tussen 50 → half 25
// dag = pos+half? Для первого поля dagVan=50, dagTot=455 (480-25) → dag=405. Не 386!
// Разница: WinPlax считает cell_w = (1440-2*60-2*80)/3=386, а frame element считает dag = 430? Не совпадает из-за разных PRESets.
// Вывод: нужно подбирать длину под WinPlax формулу.

// 4. Попытка воспроизвести точные размеры WinPlax 1440 с рамой 60 и импостом 80 через кастомный тип
// Регистрируем кастомный стиль 80×70 как в WinPlax
import { registreerStijlType } from './repos/open-pdf-studio/open-pdf-studio/js/gevelelement/catalogus.js';
registreerStijlType({id:'winplax-80x70', naam:'WinPlax 80×70', nameEn:'WinPlax 80×70', breedteMm:80, diepteMm:70, presets:['vliesgevel','kozijn']});
registreerStijlType({id:'winplax-60x70', naam:'WinPlax 60×70', nameEn:'WinPlax 60×70', breedteMm:60, diepteMm:70, presets:['vliesgevel','kozijn']});

let pWin = {
  lengte: 1440,
  stijlen: [{pos: 60+386.666/2+40, type:'winplax-80x70'}, {pos: 1440-60-386.666/2-40, type:'winplax-80x70'}],
  // Вычислим точные позиции hart: для WinPlax cell_w 386.666, kader 60, mullion 80
  // kader from 0..60 hart 30, first cell dag 60..446.666, mullion hart 486.666, second cell 526.666..913.333, mullion hart 953.333, third cell 993.333..1380
  // hart positions: 486.666 and 953.333
  kader: ['winplax-60x70','winplax-60x70'],
  panelen: [{type:'glas'},{type:'glas'},{type:'glas'}],
};
// Пересчитаем hart правильно
pWin.stijlen = [{pos: 60+386.666+40, type:'winplax-80x70'}, {pos: 60+386.666+80+386.666+40, type:'winplax-80x70'}];
console.log(`\nWinPlax hart calc: first ${(60+386.666+40).toFixed(1)} second ${(60+386.666+80+386.666+40).toFixed(1)}`);
printIndeling("OK-1 WinPlax 60/80 кастом (vliesgevel)", pWin, 'vliesgevel');

// Проверим weergave команды для DXF
import { elementMaat } from './repos/open-pdf-studio/open-pdf-studio/js/gevelelement/weergave.js';
const layWin = indeling(pWin, 'vliesgevel');
console.log(`elementMaat WinPlax:`, elementMaat(pWin, 'vliesgevel'));
console.log(`layWin velden dagMm:`, layWin.velden.map(v=>v.dagMm));
console.log(`WinPlax cell_w 386.666 vs dagMm ${layWin.velden[0].dagMm} — разница из-за того что indeling считает dag = breedte - b0/2 - bn/2? Для WinPlax dag = cell_w -?`);

// Сохраним JSON для DXF-генерации (Python потом сделает DXF)
fs.mkdirSync(OUT, {recursive:true});
fs.writeFileSync(path.join(OUT, 'open_pdf_studio_OK1_indeling.json'), JSON.stringify({
  vliesgevel_3fields: indeling(p1,'vliesgevel'),
  kozijn_3fields: indeling(p1k,'kozijn'),
  winplax_custom: indeling(pWin,'vliesgevel'),
}, null, 2));
console.log(`\nJSON saved ${OUT}/open_pdf_studio_OK1_indeling.json`);

console.log(`
ВЫВОД open-pdf-studio frame element для ОК-1:
- РЕАЛЬНЫЙ indeling() работает, даёт точные поля и stijlen, но 1D (только вдоль длины)
- Для ОК-1 3×2 нужен 2D: вертикаль 3 поля (1440→480) + горизонталь 2 поля (720) — frame element 1D не умеет одновременно 2 направления!
  → WinPlax 2D cols×rows, frame element 1D (vliesgevel вдоль, нужна вторая размерность)
- Размеры: vliesgevel 50×150 vs WinPlax 60×70/80×70 — кастомный тип 80×70 зарегистрирован, но dagMm всё равно 386+? (надо подгонять)
- Панели: glas/dicht/deur/draairaam — есть draairaam (поворотная створка) как в WinPlax TURN, но нет per-cell TURN_TILT/TILT
- Нет bead outer larger, falz 5, sill 30 — это 2D детали
- Для WinPlax полезен как idea: catalogus + indeling + weergave (filled rect mullion, double line glass)
`);
