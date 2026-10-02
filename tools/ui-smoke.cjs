/* Isolated headless tests of repository-owned fixtures only; no external requests. */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../webroot');
const out = path.resolve(process.env.UI_EVIDENCE || 'build/ui-evidence');
const assets = {'/': ['index.html','text/html'], '/index.html':['index.html','text/html'],
  '/app.js':['app.js','text/javascript'], '/style.css':['style.css','text/css']};
const server=http.createServer((req,res)=>{ const asset=assets[req.url]; if(!asset){res.writeHead(404);res.end();return;} res.writeHead(200,{'Content-Type':asset[1]});res.end(fs.readFileSync(path.join(root,asset[0]))); });
(async()=>{
  fs.mkdirSync(out,{recursive:true});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin=`http://127.0.0.1:${server.address().port}`;
  const browser=await chromium.launch({ headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {}) });
  const findings=[];
  try {
    for(const viewport of [{width:1440,height:1040},{width:393,height:852},{width:320,height:740}]){
      const context=await browser.newContext({viewport,deviceScaleFactor:1});
      await context.route('**/*',route=>new URL(route.request().url()).origin===origin ? route.continue() : route.abort());
      const page=await context.newPage(); const errors=[];
      page.on('pageerror',error=>errors.push(error.message));
      page.on('console',msg=>{ if(msg.type()==='error' && !msg.text().includes('404'))errors.push(msg.text()); });
      await page.goto(origin);
      assert.equal(await page.locator('.preview').innerText(),'交互预览 · 未连接设备');
      for(const section of ['overview','apps','performance','recovery']){
        await page.locator(`[data-page="${section}"]`).click();
        assert.equal(await page.locator('main h1').count(),1);
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`overflow at ${viewport.width}/${section}`);
        await page.screenshot({path:path.join(out,`${viewport.width}-${section}.png`),fullPage:false});
        await page.screenshot({path:path.join(out,`${viewport.width}-${section}-full.png`),fullPage:true});
      }
      await page.locator('[data-page="apps"]').click();
      assert.equal(await page.getByRole('button',{name:'模拟后台休眠',exact:true}).isDisabled(),true);
      await page.getByRole('switch').click();
      await page.getByRole('button',{name:'模拟后台休眠',exact:true}).click();
      assert.equal(await page.getByText('模拟休眠',{exact:true}).count(),1);
      await page.getByRole('button',{name:'模拟前台唤醒',exact:true}).click();
      assert.equal(await page.getByText('保持活跃',{exact:true}).count(),1);
      await page.getByRole('button',{name:'模拟后台休眠',exact:true}).click();
      await page.locator('[data-page="recovery"]').click();
      for(let i=0;i<3;i++)await page.getByRole('button',{name:'模拟一次失败',exact:true}).click();
      assert.equal(await page.getByText('已自动停用（演示）',{exact:true}).count(),1);
      assert.equal(await page.getByRole('button',{name:'模拟健康启动',exact:true}).isDisabled(),true);
      await page.locator('[data-page="apps"]').click();
      assert.equal(await page.getByRole('switch').isDisabled(),true);
      assert.equal(await page.getByText('保持活跃',{exact:true}).count(),1);
      await page.goBack();
      assert.equal(await page.locator('#breadcrumb').innerText(),'启动保护');
      await page.getByRole('button',{name:'重置演示',exact:true}).click();
      await page.locator('[data-page="performance"]').click();
      await page.getByRole('button',{name:/省电/}).click();
      assert.equal(await page.getByRole('button',{name:/省电/}).getAttribute('aria-pressed'),'true');
      await page.reload();
      assert.equal(await page.getByRole('button',{name:/均衡/}).getAttribute('aria-pressed'),'true');
      assert.deepEqual(errors,[],errors.join('\n'));
      findings.push({viewport,overflow:false,flow:'allow → sleep → wake → fail x3 → stopped → reset',errors});
      await context.close();
    }
    fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({scope:'isolated self-owned WebUI fixture; no Android/root execution',findings},null,2));
    console.log(JSON.stringify(findings,null,2));
  }finally{await browser.close();server.close();}
})().catch(err=>{console.error(err);server.close();process.exitCode=1;});
