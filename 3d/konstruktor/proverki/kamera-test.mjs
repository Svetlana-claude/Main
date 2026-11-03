// Камера держит модель в середине кадра: при открытии, при анимациях, при разборке; сдвинуть сцену нельзя.
import { chromium } from 'playwright-core';
import { readdirSync } from 'node:fs';
const kesh = process.env.HOME + '/.cache/ms-playwright/chromium-1234/';
const chrome = kesh + readdirSync(kesh).find((d) => d.startsWith('chrome-')) + '/chrome';
const b = await chromium.launch({ executablePath: chrome, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const ok = (u, t) => console.log((u ? 'OK   ' : 'FAIL ') + t);
for (const m of (process.env.MODELI || 'parashyut,samolet').split(',')) {
  const s = await b.newPage({ viewport: { width: 1280, height: 800 } });
  await s.goto(`http://127.0.0.1:8765/proverki/stend.html?m=${m}`);
  await s.waitForFunction(() => window.gotovo);
  await s.waitForTimeout(1200);
  // Где на экране середина модели и помещается ли она: по углам её рамки
  const gde = () => s.evaluate(() => {
    const p = window.prosmotr;
    const k = p.kanva.getBoundingClientRect();
    const box = new (p.modelKoren.position.constructor)();
    const pts = [];
    p.modelKoren.updateMatrixWorld(true);
    p.modelKoren.traverse((o) => {
      if (!o.geometry || !o.visible) return;
      o.geometry.computeBoundingBox();
      const bb = o.geometry.boundingBox;
      for (const x of [bb.min.x, bb.max.x]) for (const y of [bb.min.y, bb.max.y]) for (const z of [bb.min.z, bb.max.z]) {
        const v = box.clone().set(x, y, z).applyMatrix4(o.matrixWorld).project(p.kamera);
        pts.push([(v.x * 0.5 + 0.5) * k.width, (-v.y * 0.5 + 0.5) * k.height]);
      }
    });
    const xs = pts.map((q) => q[0]); const ys = pts.map((q) => q[1]);
    return { cx: (Math.min(...xs) + Math.max(...xs)) / 2 / k.width, cy: (Math.min(...ys) + Math.max(...ys)) / 2 / k.height,
      vnutri: Math.min(...xs) > -5 && Math.max(...xs) < k.width + 5 && Math.min(...ys) > -5 && Math.max(...ys) < k.height + 5 };
  });
  const vCentre = (g) => Math.abs(g.cx - 0.5) < 0.12 && Math.abs(g.cy - 0.5) < 0.12;
  let g = await gde();
  ok(vCentre(g) && g.vnutri, `${m}: при открытии модель в середине и целиком (${g.cx.toFixed(2)}, ${g.cy.toFixed(2)})`);
  const k = await s.locator('.dv-scena canvas').boundingBox();
  await s.mouse.move(k.x + k.width / 2, k.y + k.height / 2);
  await s.mouse.down({ button: 'right' });
  await s.mouse.move(k.x + k.width / 2 + 250, k.y + k.height / 2 + 150, { steps: 10 });
  await s.mouse.up({ button: 'right' });
  await s.mouse.down();
  await s.mouse.move(k.x + k.width / 2 - 300, k.y + k.height / 2 - 100, { steps: 10 });
  await s.mouse.up();
  await s.waitForTimeout(800);
  g = await gde();
  ok(vCentre(g), `${m}: после вращения и попытки сдвинуть — в середине (${g.cx.toFixed(2)}, ${g.cy.toFixed(2)})`);
  await s.evaluate(() => { const p = window.prosmotr; for (const a of p.model.animations || []) p.vklyuchit(a.id, true); p.znachenie(p.model.animations?.find((a) => a.type === 'control')?.id, 1); p.plavnoVzryv(1); });
  await s.waitForTimeout(4000);
  g = await gde();
  ok(vCentre(g), `${m}: при анимациях и разборке — в середине (${g.cx.toFixed(2)}, ${g.cy.toFixed(2)})`);
  await s.screenshot({ path: `/tmp/kam-${m}.png` });
  await s.close();
}
await b.close();
