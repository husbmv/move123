// 默认映射表迁移补种回归：fixedMappings 是首装快照，只改 DEFAULT_FIXED_MAPPINGS 老用户
// 拿不到新条目（AVS2 不识别踩过）——schemaVersion 15 一次性补种 AVS 编码并清掉已移除的
// 高误报来源；补种只跑一次，用户删掉/自建同名条目都尊重。
// 用法：node 油猴脚本/tests/fixed-mappings-seed.test.mjs
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
  slice("// src/core/categories.js", "// src/core/recognition-maps.js"),
  slice("// src/core/recognition-maps.js", "// src/config.js"),
  slice("// src/config.js", "// src/icons.js"),
  slice("// src/core/category-yaml.js", "// src/core/empty-folders.js")
].join("\n");
const driver = `;
globalThis.__seed = { normalizeConfig, inferTechnicalFields, DEFAULT_FIXED_MAPPINGS };
`;
const sandbox = { console, Date, Math, JSON, Number, String, Array, Object, Set, Map, WeakMap, RegExp, Intl, Symbol, Error, DOMException };
vm.createContext(sandbox);
vm.runInContext(code + driver, sandbox, { filename: "123-helper.user.js" });
const { normalizeConfig, inferTechnicalFields, DEFAULT_FIXED_MAPPINGS } = sandbox.__seed;

const sample = "[四川卫视4K超高清频道 故乡几万里].SCTV-4K.My.Hometown.Across.The.Ocean.2024.S01.2160p.50fps.UHDTV.AVS2.10bit.HLG.DD2.0-QHstudIo";
const codecOutputs = (config) => config.library.recognition.fixedMappings
  .filter((item) => item?.field === "videoCodec").map((item) => item?.output);
const ids = (config) => new Set(config.library.recognition.fixedMappings.map((item) => item?.id));

// 1. 老配置（schemaVersion 14 的旧表快照：无 AVS 条目）→ 补种；iT/FriDay 照常保留
const oldSnapshot = DEFAULT_FIXED_MAPPINGS
  .filter((item) => !["video-avs3", "video-avs2", "video-avs-plus"].includes(item?.id))
  .map((item) => ({ ...item }));
const legacy = normalizeConfig({
  schemaVersion: 14,
  library: { recognition: { fixedMappings: oldSnapshot } }
});
assert.deepEqual([...codecOutputs(legacy).filter((v) => String(v).startsWith("AVS"))], ["AVS3", "AVS2", "AVS+"], "老配置应补种 AVS3/AVS2/AVS+");
assert.ok(ids(legacy).has("source-it"), "iT 来源应保留（常用，撞名《IT》手动改）");
const friday = legacy.library.recognition.fixedMappings.find((item) => item?.id === "source-friday");
assert.deepEqual([...(friday?.aliases || [])], ["FriDay", "Friday影音"], "FriDay 双别名应保留");
assert.equal(legacy.schemaVersion, 16, "迁移后 schemaVersion 应写到 16");
console.log("ok 老配置补种 AVS 编码，iT/FriDay 来源保留");

// 1b. v15 中间版受害配置（source-it 被删、FriDay 裸别名被裁）→ 恢复默认条目
const victim = normalizeConfig({
  schemaVersion: 15,
  library: { recognition: { fixedMappings: [
    { id: "video-hevc", field: "videoCodec", aliases: ["HEVC"], output: "HEVC" },
    { id: "source-friday", field: "mediaSource", aliases: ["Friday影音"], output: "FriDay" }
  ] } }
});
assert.ok([...victim.library.recognition.fixedMappings].some((item) => item?.id === "source-it"), "中间版删掉的 source-it 应恢复");
const fridayRestored = victim.library.recognition.fixedMappings.find((item) => item?.id === "source-friday");
assert.deepEqual([...(fridayRestored?.aliases || [])], ["FriDay", "Friday影音"], "裸 FriDay 别名应恢复");
console.log("ok v15 中间版误删的来源条目自动恢复");

// 2. 端到端：补种后的用户映射表喂 inferTechnicalFields，AVS2 能识别
const fields = inferTechnicalFields(sample, legacy.library.recognition.fixedMappings);
assert.equal(fields.videoCodec, "AVS2");
assert.equal(fields.audioCodec, "DD.2.0");
assert.equal(fields.resourceType, "UHDTV");
console.log("ok 补种后老配置也能识别 AVS2/UHDTV/DD2.0");

// 3. 补种只跑一次：schemaVersion 16 后用户删掉 AVS2 不复活
const rerun = normalizeConfig({
  schemaVersion: 16,
  library: { recognition: { fixedMappings: legacy.library.recognition.fixedMappings.filter((item) => item?.output !== "AVS2") } }
});
assert.ok(!codecOutputs(rerun).includes("AVS2"), "用户删除后不应复活");
console.log("ok schemaVersion 16 起补种不再重跑（删除不复活）");

// 4. 用户已自建同名输出 → 不重复补种
const custom = normalizeConfig({
  schemaVersion: 14,
  library: { recognition: { fixedMappings: [
    { id: "custom-avs2", field: "videoCodec", aliases: ["AVS2", " avs2 "], output: "AVS2" }
  ] } }
});
assert.equal(codecOutputs(custom).filter((v) => v === "AVS2").length, 1, "自建 AVS2 不重复");
console.log("ok 用户自建同名条目时不重复补种");

// 5. 全新安装：走 DEFAULT_CONFIG，本身就有 AVS 与 iT/FriDay 来源
const fresh = normalizeConfig(null);
assert.ok(codecOutputs(fresh).includes("AVS2"), "新装默认表应含 AVS2");
assert.ok(ids(fresh).has("source-it"), "新装默认表含 iT 来源");
assert.ok(DEFAULT_FIXED_MAPPINGS.some((item) => item?.id === "video-avs2"), "DEFAULT_FIXED_MAPPINGS 应含 AVS2");
console.log("ok 新装默认表自带 AVS 编码与常用来源");

// 6. SDR 一律不标注：fixedMappings 是首装快照，1.4.7 及更早种下的 dynamic-sdr 条目不会
// 因为默认表删了条目就自己消失（「SDR 还是能识别到」的根因）。归一化这道闸必须把存量
// 快照里的 SDR 条目与 SDR 别名都剥掉，且不碰「VIVID SDR → EDR」这类高规格别名。
const sdrName = "Movie.2024.1080p.WEB-DL.HEVC.AAC.SDR";
const legacySdr = normalizeConfig({
  schemaVersion: 16,
  library: { recognition: { fixedMappings: [
    { id: "dynamic-hdr10", field: "dynamicRange", aliases: ["HDR10", "HDR 10"], output: "HDR10" },
    { id: "dynamic-sdr", field: "dynamicRange", aliases: ["SDR"], output: "SDR" },
    // 别名里混着 SDR 的老条目：剥别名、留条目，否则纯 SDR 文件会被误判成 HDR
    { id: "custom-range", field: "dynamicRange", aliases: ["HDR", "sdr"], output: "HDR" },
    { id: "quality-edr", field: "highQuality", aliases: ["EDR", "VIVID SDR"], output: "EDR" }
  ] } }
});
const sdrOutputs = legacySdr.library.recognition.fixedMappings.filter((item) => item?.field === "dynamicRange").map((item) => item?.output);
assert.deepEqual([...sdrOutputs], ["HDR10", "HDR"], "存量快照里的 SDR 条目应被剥掉，其余动态范围条目原样保留");
assert.deepEqual([...(legacySdr.library.recognition.fixedMappings.find((item) => item?.id === "custom-range")?.aliases || [])], ["HDR"], "动态范围条目里的 SDR 别名应被剥掉");
const sdrFields = inferTechnicalFields(sdrName, legacySdr.library.recognition.fixedMappings);
assert.equal(sdrFields.dynamicRange, "", `SDR 不该成为动态范围: ${sdrFields.dynamicRange}`);
assert.equal(sdrFields.effect, "", `SDR 不该进 effect: ${sdrFields.effect}`);
const hdrFields = inferTechnicalFields("Movie.2024.1080p.WEB-DL.HDR10.HEVC.AAC", legacySdr.library.recognition.fixedMappings);
assert.equal(hdrFields.dynamicRange, "HDR10", "剥 SDR 别名后真档位照常识别");
const edrFields = inferTechnicalFields("Movie.2024.1080p.WEB-DL.VIVID.SDR.HEVC.AAC", legacySdr.library.recognition.fixedMappings);
assert.equal(edrFields.highQuality, "EDR", "「VIVID SDR」是高规格/EDR 的别名，不能被 SDR 闸误伤");
console.log("ok 存量快照里的 SDR 条目/别名被剥掉，真档位与 EDR 别名不受影响");

console.log("fixed-mappings-seed.test.mjs 全部通过");
