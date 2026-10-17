// AI 辅助识别回归测试：接口地址拼装、防御性 JSON 解析、识别/重排结果解析、候选歧义判定
// 与 AI 重排采纳逻辑。纯 Node 运行，不打网络（AiClient 的真实网络层不在本用例覆盖范围）。
// 用法：node 油猴脚本/123-helper/tests/ai-assist.test.mjs
import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const scriptPath = fileURLToPath(new URL("../123-helper.user.js", import.meta.url));
const lines = fs.readFileSync(scriptPath, "utf8").split("\n");
const slice = (fromMarker, toMarker) => {
  const start = lines.findIndex((line) => line.includes(fromMarker));
  const end = lines.findIndex((line) => line.includes(toMarker));
  if (start < 0 || end <= start) throw new Error(`bundle markers not found: ${fromMarker} .. ${toMarker}`);
  return lines.slice(start, end).join("\n");
};
const code = [
  slice("// src/core/utils.js", "// src/api.js"),
  slice("// src/core/categories.js", "// src/icons.js"),
  slice("// src/core/category-yaml.js", "// src/core/empty-folders.js")
].join("\n");
const driver = `;
globalThis.__ai = {
  AiClient, aiApiBase, aiChatEndpoint, parseAiJsonObject, parseAiRecognitionResult,
  parseAiRerankIndex, buildAiRecognitionMessages, buildAiRerankMessages,
  buildAiRecognitionBatchMessages, parseAiRecognitionBatchResult,
  aiRerankShortlist, aiRerankCandidate, normalizeTmdbMedia
};
`;
const sandbox = { console, Date, Math, JSON, Number, String, Array, Object, Set, Map, RegExp, Intl, Symbol, Error, DOMException, Promise, Boolean, isNaN, parseInt, parseFloat, setTimeout, clearTimeout };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(code + driver, sandbox, { filename: "123-helper.user.js" });
// 重试逻辑会 sleep 600–1000ms：测试里短路掉，避免拖慢用例。
sandbox.sleep = () => Promise.resolve();
const { AiClient, aiApiBase, aiChatEndpoint, parseAiJsonObject, parseAiRecognitionResult, parseAiRerankIndex, buildAiRecognitionMessages, buildAiRerankMessages, buildAiRecognitionBatchMessages, parseAiRecognitionBatchResult, aiRerankShortlist, aiRerankCandidate } = sandbox.__ai;

let passed = 0;
let chain = Promise.resolve();
const test = (title, fn) => {
  chain = chain.then(async () => {
    await fn();
    passed += 1;
    console.log(`  ok ${title}`);
  });
};

// —— 接口地址拼装（OpenAI 兼容：DeepSeek / OpenAI / 本地 Ollama 一套逻辑）——
test("aiApiBase 缺省用 DeepSeek", () => assert.equal(aiApiBase({}), "https://api.deepseek.com/v1"));
test("aiApiBase 没写协议头按 https 补全并去尾斜杠", () => assert.equal(aiApiBase({ apiBase: "api.openai.com/v1/" }), "https://api.openai.com/v1"));
test("aiChatEndpoint 在 /v1 后补 /chat/completions", () => assert.equal(aiChatEndpoint({ apiBase: "https://api.deepseek.com/v1" }), "https://api.deepseek.com/v1/chat/completions"));
test("aiChatEndpoint 已带 /chat/completions 不重复追加", () => assert.equal(aiChatEndpoint({ apiBase: "http://localhost:11434/v1/chat/completions" }), "http://localhost:11434/v1/chat/completions"));

// —— 防御性 JSON 解析（模型常在 JSON 后补解释；片名里也可能带花括号）——
test("parseAiJsonObject 抠出代码块里的 JSON", () => assert.deepEqual(parseAiJsonObject("```json\n{\"index\":2}\n```"), { index: 2 }));
test("parseAiJsonObject 容忍 JSON 后面的解释文字", () => assert.deepEqual(parseAiJsonObject('{"index":1} 因为目录名带全集'), { index: 1 }));
test("parseAiJsonObject 忽略字符串里的花括号", () => assert.deepEqual(parseAiJsonObject('{"title":"含 {括号} 的片名","year":"2024"}'), { title: "含 {括号} 的片名", year: "2024" }));
test("parseAiJsonObject 括号不配对返回 null", () => assert.equal(parseAiJsonObject('{"index":1'), null));
test("parseAiJsonObject 空文本返回 null", () => assert.equal(parseAiJsonObject(""), null));

// —— AI 识别结果解析 ——
test("parseAiRecognitionResult 规范化字段（类型转小写、年份校验）", () => {
  const result = parseAiRecognitionResult('{"title":"The Workplace","original_title":"初入职场","year":"2025","media_type":"TV","season":1,"episode":9,"confidence":0.8}');
  assert.equal(result.title, "The Workplace");
  assert.equal(result.originalTitle, "初入职场");
  assert.equal(result.mediaType, "tv");
  assert.equal(result.year, "2025");
  assert.equal(result.season, 1);
  assert.equal(result.episode, 9);
  assert.equal(result.confidence, 0.8);
});
test("parseAiRecognitionResult 非法年份/类型/季集一律留空", () => {
  const result = parseAiRecognitionResult('{"title":"某剧","year":"798","media_type":"anime","season":-1,"episode":0}');
  assert.equal(result.title, "某剧");
  assert.equal(result.year, "");
  assert.equal(result.mediaType, "");
  assert.equal(result.season, 0);
  assert.equal(result.episode, 0);
});
test("parseAiRecognitionResult 无 JSON 返回 null", () => assert.equal(parseAiRecognitionResult("我不知道这是什么"), null));

// —— 候选重排结果解析 ——
test("parseAiRerankIndex 取回合法序号", () => assert.equal(parseAiRerankIndex('{"index":2}', 5), 2));
test("parseAiRerankIndex 越界/负值/非整数/无 JSON 一律返回 null", () => {
  assert.equal(parseAiRerankIndex('{"index":9}', 5), null);
  assert.equal(parseAiRerankIndex('{"index":-1}', 5), null);
  assert.equal(parseAiRerankIndex('{"index":1.5}', 5), null);
  assert.equal(parseAiRerankIndex("都不匹配", 5), null);
});

// —— 提示词组装 ——
test("buildAiRecognitionMessages 带上目录名/文件名并要求只输出 JSON", () => {
  const messages = buildAiRecognitionMessages("Naruto.INTEGRALE.MULTI.VFF.1080p", ["Naruto.S01E01.mkv", "Naruto.S01E02.mkv"]);
  assert.equal(messages.length, 2);
  assert.equal(messages[0].role, "system");
  assert.equal(messages[1].role, "user");
  assert.ok(messages[1].content.includes("Naruto.INTEGRALE"));
  assert.ok(messages[1].content.includes("Naruto.S01E01.mkv"));
  assert.ok(messages[0].content.includes("JSON"));
});
test("buildAiRerankMessages 交代季播年/合集语境并列出候选", () => {
  const messages = buildAiRerankMessages(
    { folder: "Naruto.INTEGRALE", files: ["Naruto.S01E01.mkv"], title: "Naruto", year: "2002", media_type: "tv" },
    [{ index: 0, title: "火影忍者", year: "2002" }, { index: 1, title: "火影忍者 疾风传", year: "2007" }]
  );
  assert.ok(messages[0].content.includes("全季"));
  const payload = JSON.parse(messages[1].content);
  assert.equal(payload.folder, "Naruto.INTEGRALE");
  assert.equal(payload.candidates.length, 2);
});

// —— 候选歧义判定（明确命中的正常资源不能被误触发）——
const cand = (id, title, year, mediaType) => ({ id, media_type: mediaType, title, original_title: title, release_date: year ? `${year}-01-01` : "" });
test("aiRerankShortlist 精确命中不触发复核", () => {
  const fields = { title: "小黄人大眼萌3", year: "2026", mediaType: "movie" };
  const candidates = [cand(1315772, "小黄人大眼萌3", "2026", "movie"), cand(999, "小黄人", "2015", "movie")];
  const decision = aiRerankShortlist(candidates, fields);
  assert.equal(decision.uncertain, false);
  assert.equal(decision.shortlist.length, 2);
});
test("aiRerankShortlist 前二接近时触发复核", () => {
  const fields = { title: "Naruto", year: "", mediaType: "tv" };
  const candidates = [cand(1, "火影忍者 疾风传", "", "tv"), cand(2, "火影忍者", "", "tv")];
  const decision = aiRerankShortlist(candidates, fields);
  assert.equal(decision.uncertain, true);
  assert.equal(decision.shortlist.length, 2);
});
test("aiRerankShortlist 最高分不够硬时触发复核", () => {
  const fields = { title: "Vol 1", year: "", mediaType: "" };
  const decision = aiRerankShortlist([cand(3, "Kill Bill: Volume 1", "", "movie")], fields);
  assert.equal(decision.uncertain, true);
});

// —— AI 重排采纳：脚本把热度更高的续作排在前面时，AI 能改选正确的那条 ——
test("aiRerankCandidate 采纳 AI 选中的候选（改选续作之外的正篇）", async () => {
  const fields = { title: "Naruto", year: "", mediaType: "tv" };
  const candidates = [cand(1, "火影忍者 疾风传", "", "tv"), cand(2, "火影忍者", "", "tv")];
  const group = { title: "Naruto.INTEGRALE.MULTI.VFF.1080p", files: [{ name: "Naruto.S01E01.mkv" }] };
  const fakeAi = { complete: async () => '{"index":1,"confidence":0.9}' };
  const picked = await aiRerankCandidate(fakeAi, group, fields, candidates, candidates[0], {});
  assert.ok(picked, "AI 改选后应返回候选对象");
  assert.equal(picked.id, 2);
});
test("aiRerankCandidate AI 指向脚本原选择时不重复改选", async () => {
  const fields = { title: "Naruto", year: "", mediaType: "tv" };
  const candidates = [cand(1, "火影忍者 疾风传", "", "tv"), cand(2, "火影忍者", "", "tv")];
  const group = { title: "Naruto.INTEGRALE", files: [{ name: "Naruto.S01E01.mkv" }] };
  const fakeAi = { complete: async () => '{"index":0}' };
  const picked = await aiRerankCandidate(fakeAi, group, fields, candidates, candidates[0], {});
  assert.equal(picked, null, "AI 与脚本选择一致时不应改选");
});
test("aiRerankCandidate 无歧义时不调用 AI", async () => {
  const fields = { title: "小黄人大眼萌3", year: "2026", mediaType: "movie" };
  const candidates = [cand(1315772, "小黄人大眼萌3", "2026", "movie"), cand(999, "小黄人", "2015", "movie")];
  let called = false;
  const fakeAi = { complete: async () => { called = true; return '{"index":1}'; } };
  const picked = await aiRerankCandidate(fakeAi, { title: "小黄人大眼萌3", files: [] }, fields, candidates, candidates[0], {});
  assert.equal(picked, null);
  assert.equal(called, false, "明确命中不应触发 AI 调用");
});

// —— 可用性判定 ——
test("AiClient.available 需要启用+密钥+模型三者齐备", () => {
  assert.equal(new AiClient(() => ({ enabled: true, credential: "sk-x", model: "deepseek-flash" })).available(), true);
  assert.equal(new AiClient(() => ({ enabled: false, credential: "sk-x", model: "deepseek-flash" })).available(), false);
  assert.equal(new AiClient(() => ({ enabled: true, credential: "", model: "deepseek-flash" })).available(), false);
  assert.equal(new AiClient(() => ({ enabled: true, credential: "sk-x", model: "" })).available(), false);
});

// —— 熔断：密钥填错时不至于对每个未识别组反复打无效请求 ——
test("AiClient 连续失败达阈值后熔断，不再发请求", async () => {
  let calls = 0;
  sandbox.fetch = () => { calls += 1; return Promise.reject(new Error("boom")); };
  const client = new AiClient(() => ({ enabled: true, credential: "sk-bad", model: "deepseek-flash", apiBase: "https://api.deepseek.com/v1" }));
  for (let index = 0; index < 3; index += 1) await client.complete([{ role: "user", content: `hi${index}` }]).catch(() => {});
  assert.equal(client.available(), false, "连续失败后应熔断");
  await assert.rejects(() => client.complete([{ role: "user", content: "again" }]), /熔断/);
  assert.equal(calls, 3, "熔断后不应再发请求");
});
test("AiClient 改了密钥后熔断自动解除", async () => {
  sandbox.fetch = () => Promise.reject(new Error("boom"));
  let credential = "sk-bad-1";
  const client = new AiClient(() => ({ enabled: true, credential, model: "deepseek-flash", apiBase: "https://api.deepseek.com/v1" }));
  for (let index = 0; index < 3; index += 1) await client.complete([{ role: "user", content: `x${index}` }]).catch(() => {});
  assert.equal(client.available(), false);
  credential = "sk-bad-2";
  assert.equal(client.available(), true, "换密钥后应自动解除熔断");
});
test("AiClient 中间成功一次即清零失败计数，不误熔断", async () => {
  let ok = false;
  sandbox.fetch = () => ok
    ? Promise.resolve({ ok: true, json: async () => ({ choices: [{ message: { content: "{\"index\":0}" } }] }) })
    : Promise.reject(new Error("boom"));
  const client = new AiClient(() => ({ enabled: true, credential: "sk-ok", model: "deepseek-flash", apiBase: "https://api.deepseek.com/v1" }));
  await client.complete([{ role: "user", content: "a" }]).catch(() => {});
  await client.complete([{ role: "user", content: "b" }]).catch(() => {});
  ok = true;
  assert.equal(await client.complete([{ role: "user", content: "c" }]), "{\"index\":0}");
  assert.equal(client.available(), true);
});

// —— 批量打包：多个目录一次请求 ——
test("buildAiRecognitionBatchMessages 打包多个目录并要求按 key 回填", () => {
  const messages = buildAiRecognitionBatchMessages([
    { key: "g1", folder: "Naruto.INTEGRALE", files: ["Naruto.S01E01.mkv"] },
    { key: "g2", folder: "Vol 1", files: [] }
  ]);
  assert.ok(messages[0].content.includes("results"));
  const payload = JSON.parse(messages[1].content);
  assert.equal(payload.length, 2);
  assert.equal(payload[0].key, "g1");
  assert.equal(payload[1].folder, "Vol 1");
});
test("parseAiRecognitionBatchResult 按 key 归位，忽略多余项", () => {
  const text = '{"results":[{"key":"g2","title":"Kill Bill","year":"2003","media_type":"movie"},{"key":"g1","title":"火影忍者","media_type":"tv"},{"key":"g9","title":"无关项"}]}';
  const map = parseAiRecognitionBatchResult(text, ["g1", "g2"]);
  assert.equal(map.size, 2);
  assert.equal(map.get("g1").mediaType, "tv");
  assert.equal(map.get("g2").title, "Kill Bill");
  assert.equal(map.get("g2").year, "2003");
});
test("parseAiRecognitionBatchResult 没有数组/无 JSON 时返回 null", () => {
  assert.equal(parseAiRecognitionBatchResult('{"foo":1}', ["g1"]), null);
  assert.equal(parseAiRecognitionBatchResult("随便说说", ["g1"]), null);
});

// —— 并发闸：同时在飞的模型请求不超过 2 ——
test("AiClient 并发闸把同时在飞的请求限制在 2", async () => {
  const gates = [];
  sandbox.fetch = () => new Promise((resolve) => gates.push(resolve));
  const client = new AiClient(() => ({ enabled: true, credential: "sk-gate", model: "deepseek-flash", apiBase: "https://api.deepseek.com/v1" }));
  const jobs = [0, 1, 2, 3, 4].map((index) => client.complete([{ role: "user", content: `m${index}` }]).then(() => null, () => null));
  let maxActive = 0;
  const reply = { ok: true, json: async () => ({ choices: [{ message: { content: "{\"index\":0}" } }] }) };
  for (let round = 0; round < 200; round += 1) {
    maxActive = Math.max(maxActive, client.active);
    if (gates.length) gates.shift()(reply);
    await Promise.resolve();
    if (client.active === 0 && gates.length === 0) break;
  }
  await Promise.all(jobs);
  assert.equal(maxActive, 2, `同时在飞应恰好被限到 2，实际 ${maxActive}`);
  assert.equal(client.active, 0, "全部完成后名额应归零");
});

// —— 瞬时故障重试一次 ——
test("AiClient 瞬时故障先重试一次再成功", async () => {
  let calls = 0;
  sandbox.fetch = () => {
    calls += 1;
    if (calls === 1) return Promise.reject(new Error("AI 请求超时"));
    return Promise.resolve({ ok: true, json: async () => ({ choices: [{ message: { content: "{\"index\":0}" } }] }) });
  };
  const client = new AiClient(() => ({ enabled: true, credential: "sk-retry", model: "deepseek-flash", apiBase: "https://api.deepseek.com/v1" }));
  assert.equal(await client.complete([{ role: "user", content: "retry" }]), "{\"index\":0}");
  assert.equal(calls, 2, "应先失败一次、重试一次");
  assert.equal(client.available(), true);
});

// —— 缓存策略：只缓存解析得出来的结果 ——
test("AiClient 解析不出的结果不入缓存，会再次请求", async () => {
  let calls = 0;
  sandbox.fetch = () => { calls += 1; return Promise.resolve({ ok: true, json: async () => ({ choices: [{ message: { content: "这里没有 JSON" } }] }) }); };
  const client = new AiClient(() => ({ enabled: true, credential: "sk-neg", model: "deepseek-flash", apiBase: "https://api.deepseek.com/v1" }));
  const messages = [{ role: "user", content: "validate-bad" }];
  const validate = (value) => Boolean(parseAiRecognitionResult(value));
  await client.complete(messages, { validate });
  await client.complete(messages, { validate });
  assert.equal(calls, 2, "解析不出的结果不该进缓存");
});
test("AiClient 解析得出来才入缓存，重复请求不再打网络", async () => {
  let calls = 0;
  sandbox.fetch = () => { calls += 1; return Promise.resolve({ ok: true, json: async () => ({ choices: [{ message: { content: "{\"title\":\"某剧\"}" } }] }) }); };
  const client = new AiClient(() => ({ enabled: true, credential: "sk-pos", model: "deepseek-flash", apiBase: "https://api.deepseek.com/v1" }));
  const messages = [{ role: "user", content: "validate-good" }];
  const validate = (value) => Boolean(parseAiRecognitionResult(value));
  await client.complete(messages, { validate });
  await client.complete(messages, { validate });
  assert.equal(calls, 1, "解析成功的结果应命中缓存");
});

await chain;
console.log(`\nai-assist: ${passed} passed`);
