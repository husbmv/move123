// CureTMDb 社区分季表回归测试：镜像回退（jsDelivr → raw.githubusercontent）、失败抛错与 24h 缓存。
// 纯 Node 运行，网络层用假 gmRequest 注入。
// 用法：node 油猴脚本/123-helper/tests/curetmdb-mirror.test.mjs
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
  slice("// src/core/category-yaml.js", "// src/core/empty-folders.js"),
  slice("// src/tmdb.js", "// src/metadata.js")
].join("\n");
const driver = `;
globalThis.__cure = { CURE_TMDB_TV_JSON_URLS, CURE_TMDB_TV_FETCH_TIMEOUT, loadCureTmdbTvMap, loadCureTmdbTvStructure };
`;
const sandbox = { console, Date, Math, JSON, Number, String, Array, Object, Set, Map, RegExp, Intl, Symbol, Error, DOMException, Promise, Boolean };
sandbox.globalThis = sandbox;
// 存储与网络层注入：只需覆盖外部依赖，不用把 fastlink 整段拖进来。
const store = new Map();
sandbox.checkpointStorageGet = (key) => (store.has(key) ? store.get(key) : null);
sandbox.checkpointStorageSet = (key, value) => { store.set(key, value); };
vm.createContext(sandbox);
vm.runInContext(code + driver, sandbox, { filename: "123-helper.user.js" });
const { CURE_TMDB_TV_JSON_URLS, CURE_TMDB_TV_FETCH_TIMEOUT, loadCureTmdbTvMap, loadCureTmdbTvStructure } = sandbox.__cure;

let passed = 0;
let chain = Promise.resolve();
const test = (title, fn) => {
  chain = chain.then(async () => {
    await fn();
    passed += 1;
    console.log(`  ok ${title}`);
  });
};

const FIXTURE = {
  "223564": { name: "超超超超超喜欢你的100个女朋友", seasons: [{ season_number: 1, name: "第一季", episode_count: 12 }, { season_number: 2, name: "第二季", episode_count: 12 }] }
};

test("镜像顺序：优先 jsDelivr，回退 raw.githubusercontent", () => {
  assert.equal(CURE_TMDB_TV_JSON_URLS[0], "https://cdn.jsdelivr.net/gh/wikrin/CureTMDb@main/tv.json");
  assert.equal(CURE_TMDB_TV_JSON_URLS[1], "https://raw.githubusercontent.com/wikrin/CureTMDb/main/tv.json");
  assert.ok(CURE_TMDB_TV_FETCH_TIMEOUT > 0 && CURE_TMDB_TV_FETCH_TIMEOUT <= 15000, "外部源要有较短超时，别拖住弹窗");
});
test("首个镜像失败时自动回退到下一个并写缓存", async () => {
  store.clear();
  const tried = [];
  sandbox.gmRequest = async (url) => {
    tried.push(url);
    if (url === CURE_TMDB_TV_JSON_URLS[0]) throw new Error("jsDelivr 不可达");
    return FIXTURE;
  };
  const map = await loadCureTmdbTvMap();
  assert.equal(tried.length, 2, "应先试 jsDelivr，失败再回退 raw");
  assert.equal(map["223564"].name, "超超超超超喜欢你的100个女朋友");
  const before = tried.length;
  const again = await loadCureTmdbTvMap();
  assert.equal(tried.length, before, "第二次应命中 24h 缓存，不再发请求");
  assert.deepEqual(again, map);
});
test("两个镜像都失败时抛最后一条错误", async () => {
  store.clear();
  sandbox.gmRequest = async () => { throw new Error("网络不可达"); };
  await assert.rejects(() => loadCureTmdbTvMap(), /网络不可达/);
});
test("loadCureTmdbTvStructure 按 TMDB id 取结构；未收录返回 null", async () => {
  store.clear();
  sandbox.gmRequest = async () => FIXTURE;
  const structure = await loadCureTmdbTvStructure(223564);
  assert.ok(structure, "应返回结构");
  assert.equal(structure.source, "curetmdb");
  assert.equal(structure.seasons.length, 2);
  assert.equal(structure.seasons[0].count, 12);
  assert.equal(await loadCureTmdbTvStructure(999999), null, "社区表未收录应返回 null");
});

await chain;
console.log(`\ncuretmdb-mirror: ${passed} passed`);
