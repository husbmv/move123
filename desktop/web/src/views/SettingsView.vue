<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useTheme } from "@/composables/useTheme";
import { useGlobalState } from "@/composables/useGlobalState";
import { useUpdater } from "@/composables/useUpdater";
import { adminApi, poolApi, type PoolTokenStatus } from "@/api";
import { displayName, formatBytes } from "@/utils/format";
import PageHero from "@/components/PageHero.vue";
import GlassCard from "@/components/GlassCard.vue";
import FormField from "@/components/FormField.vue";

interface DesktopInfo {
  isDesktop: boolean;
  platform: string;
  dataDir: string;
  port: number;
  fixedPort: number | null;
  versions: {
    app: string;
    electron: string;
  };
}

const { theme, setTheme } = useTheme();
const { state, notifySuccess, notifyError, confirm, loadStatus } = useGlobalState();
const webAuthEnabled = ref(false);
const accountUsername = ref("admin");
const accountNewUsername = ref("");
const currentPassword = ref("");
const newPassword = ref("");
const passwordSaving = ref(false);
const proxyUrl = ref("");
const proxySaving = ref(false);

async function saveWebProxy() {
  proxySaving.value = true;
  try {
    const response = await fetch("/api/web-auth/proxy", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ url: proxyUrl.value.trim() }),
    });
    if (!response.ok) throw new Error((await response.json()).detail || "保存失败");
    notifySuccess("TG 与 TMDB 代理已保存并生效");
  } catch (error) {
    notifyError(error instanceof Error ? error.message : "保存失败");
  } finally {
    proxySaving.value = false;
  }
}

async function changeWebPassword() {
  passwordSaving.value = true;
  try {
    const response = await fetch("/api/web-auth/password", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username: accountUsername.value, currentPassword: currentPassword.value, newPassword: newPassword.value, newUsername: accountNewUsername.value }),
    });
    if (!response.ok) throw new Error((await response.json()).detail || "修改失败");
    currentPassword.value = "";
    newPassword.value = "";
    notifySuccess("后台账号已修改，请重新登录");
    window.location.assign("/admin/login");
  } catch (error) {
    notifyError(error instanceof Error ? error.message : "修改失败");
  } finally {
    passwordSaving.value = false;
  }
}

async function logoutWeb() {
  await fetch("/api/web-auth/logout", { method: "POST" });
  window.location.assign("/admin/login");
}

const desktopInfo = ref<DesktopInfo | null>(null);
const backendVersion = computed(() => (state.status ? "已连接" : "未连接"));

// ===== 123 网盘授权（OAuth，账号密码在 123 官方授权页输入） =====
const pan123 = computed(() => state.status?.pan123);
const pan123Authenticated = computed(() => Boolean(pan123.value?.authenticated));
const pan123LoginExpired = computed(() => Boolean(pan123.value?.loginExpired));
const pan123AccessOnly = computed(() => Boolean(pan123.value?.accessOnly));
const pan123Profile = computed(() => pan123.value?.profile || null);
const pan123Name = computed(() => displayName(pan123Profile.value || null, pan123.value?.user || ""));
const pan123Space = computed(() => {
  const profile = pan123Profile.value;
  if (!profile) return "";
  const used = formatBytes(profile.spaceUsed);
  const total = formatBytes(profile.spacePermanent);
  if (used && total) return `${used} / ${total}`;
  return used || (total ? `总容量 ${total}` : "");
});

const authorizing = ref(false);
const unbinding = ref(false);
const browserAuthOpen = ref(false);
const authorizeUrl = ref("");
const authorizeNonce = ref("");
const callbackInput = ref("");
const finishing = ref(false);
const readingCallback = ref(false);

interface OauthPopupResult {
  callbackUrl?: string;
  cancelled?: boolean;
  error?: string;
}

function desktopBridge() {
  return (window as unknown as {
    cloud123?: {
      openPan123Oauth?: (payload: { authorizeUrl: string; redirectUri: string }) => Promise<OauthPopupResult>;
      getInfo?: () => Promise<DesktopInfo>;
      openDataDir?: () => Promise<string>;
      getPortConfig?: () => Promise<{ port: number | null }>;
      setPortConfig?: (payload: { port: number | null }) => Promise<{ port: number | null }>;
      relaunchApp?: () => Promise<boolean>;
    };
  }).cloud123;
}

async function authorizePan123() {
  const bridge = desktopBridge();
  // window.open 必须在用户点击事件的同步阶段调用；等待 API 后再调用会被浏览器拦截。
  const popup = bridge?.openPan123Oauth ? null : window.open("about:blank", "_blank");
  if (popup) {
    popup.document.title = "123 云盘授权准备中";
    popup.document.body.textContent = "正在获取 123 云盘官方授权地址，请稍候…";
  }
  authorizing.value = true;
  try {
    const start = await adminApi.oauthStart();
    if (bridge?.openPan123Oauth) {
      // 桌面端：弹窗打开 123 官方授权页（账号密码在官方页输入），自动截获回调
      const result = await bridge.openPan123Oauth({ authorizeUrl: start.authorizeUrl, redirectUri: start.redirectUri });
      if (result?.cancelled) {
        notifyError("授权窗口已关闭，未完成授权");
        return;
      }
      if (!result?.callbackUrl) {
        notifyError(result?.error || "授权未完成，请重试");
        return;
      }
      await adminApi.oauthFinish(start.nonce, result.callbackUrl);
      notifySuccess("123 网盘授权成功");
      await loadStatus();
    } else {
      // 浏览器模式：尝试打开预先创建的标签；被拦截时仍可点击下方链接手动打开。
      authorizeUrl.value = start.authorizeUrl;
      authorizeNonce.value = start.nonce;
      callbackInput.value = "";
      browserAuthOpen.value = true;
      if (popup && !popup.closed) {
        popup.opener = null;
        popup.location.href = start.authorizeUrl;
      }
    }
  } catch (error) {
    if (popup && !popup.closed) popup.close();
    notifyError(`发起授权失败：${error instanceof Error ? error.message : String(error)}`);
  } finally {
    authorizing.value = false;
  }
}

async function importAccessToken() {
  const value = callbackInput.value.trim();
  if (!value) {
    notifyError("请先粘贴 123 访问令牌");
    return;
  }
  finishing.value = true;
  try {
    await adminApi.oauthImportAccess(value);
    browserAuthOpen.value = false;
    authorizeUrl.value = "";
    callbackInput.value = "";
    notifySuccess("访问令牌已保存；到期后需重新授权");
    await loadStatus();
  } catch (error) {
    notifyError(`访问令牌导入失败：${error instanceof Error ? error.message : String(error)}`);
  } finally {
    finishing.value = false;
  }
}

async function finishBrowserAuth() {
  const value = callbackInput.value.trim();
  if (!value) {
    notifyError("请粘贴授权后的完整回调地址、刷新令牌或访问令牌");
    return;
  }
  finishing.value = true;
  try {
    if (value.toLowerCase().startsWith("http")) {
      if (value.includes("#") && !value.includes("?code=")) {
        const parsed = new URL(value);
        const redirect = authorizeUrl.value ? new URL(authorizeUrl.value).searchParams.get("redirect_uri") : null;
        const expected = redirect ? new URL(redirect) : null;
        if (!expected || parsed.origin !== expected.origin) {
          throw new Error("回调地址来源不匹配，请复制本次授权的完整地址");
        }
      }
      await adminApi.oauthFinish(authorizeNonce.value, value);
    } else {
      const kind = tokenKind(value);
      if (kind === "access") {
        await adminApi.oauthImportAccess(value);
      } else {
        await adminApi.oauthImport(value);
      }
    }
    browserAuthOpen.value = false;
    authorizeUrl.value = "";
    callbackInput.value = "";
    notifySuccess(tokenKind(value) === "access" ? "访问令牌已导入；到期后需重新授权" : "123 网盘授权成功");
    await loadStatus();
  } catch (error) {
    notifyError(`授权失败：${error instanceof Error ? error.message : String(error)}`);
  } finally {
    finishing.value = false;
  }
}

function tokenKind(value: string): "access" | "refresh" {
  const parts = value.split(".");
  if (parts.length !== 3) return "refresh";
  try {
    const payload = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
    if (typeof payload?.exp === "number") return "access";
  } catch { /* 不是 JWT，按刷新令牌交由后端校验。 */ }
  return "refresh";
}

async function pasteAndFinishBrowserAuth() {
  readingCallback.value = true;
  try {
    if (!navigator.clipboard?.readText) {
      throw new Error("当前浏览器不支持读取剪贴板，请手动粘贴回调地址");
    }
    const value = (await navigator.clipboard.readText()).trim();
    if (!value) throw new Error("剪贴板为空，请先复制授权完成页的完整地址");
    const parsed = new URL(value);
    const redirect = authorizeUrl.value ? new URL(authorizeUrl.value).searchParams.get("redirect_uri") : null;
    const expected = redirect ? new URL(redirect) : null;
    const matchesCallback = expected && parsed.origin === expected.origin && parsed.pathname === expected.pathname;
    const matchesTokenPage = expected && parsed.origin === expected.origin && parsed.pathname === "/" && parsed.hash.length > 1;
    if (!matchesCallback && !matchesTokenPage) {
      throw new Error("剪贴板不是本次 123 授权的回调地址；请复制授权完成页地址栏的完整 URL");
    }
    callbackInput.value = value;
    await finishBrowserAuth();
  } catch (error) {
    notifyError(error instanceof Error ? error.message : "读取剪贴板失败，请手动粘贴回调地址");
  } finally {
    readingCallback.value = false;
  }
}

async function unbindPan123() {
  const ok = await confirm("解除绑定后，投稿归属判断与他人分享的自动转存、123 相关搬运将不可用，确定解除吗？", "解除绑定 123 网盘");
  if (!ok) return;
  unbinding.value = true;
  try {
    await adminApi.logout();
    notifySuccess("已解除绑定");
    await loadStatus();
  } catch (error) {
    notifyError(`解除绑定失败：${error instanceof Error ? error.message : String(error)}`);
  } finally {
    unbinding.value = false;
  }
}

const themeOptions = [
  { value: "auto" as const, label: "跟随系统", icon: "mdi-theme-light-dark", desc: "与操作系统保持一致" },
  { value: "light" as const, label: "浅色", icon: "mdi-white-balance-sunny", desc: "明亮的冰玻璃" },
  { value: "dark" as const, label: "深色", icon: "mdi-moon-waning-crescent", desc: "深空极光玻璃" },
];

// ===== 软件更新 =====
const updater = useUpdater();
const appVersion = computed(() => desktopInfo.value?.versions?.app || "");

const updateStatusText = computed(() => {
  const version = updater.state.info?.version || "";
  switch (updater.state.status) {
    case "checking":
      return "正在检查更新…";
    case "downloading":
      return updater.state.percent
        ? `正在下载新版本 ${version}（${updater.state.percent}%）`
        : `正在下载新版本 ${version}…`;
    case "downloaded":
      return `新版本 ${version} 已就绪，点击「重启并安装」完成升级。`;
    case "installing":
      return "正在安装更新，应用即将重启…";
    case "none":
      return `已是最新版本${version ? `（${version}）` : ""}。`;
    case "update-manual":
      return `发现新版本 ${version}；该版本未包含自动更新组件，请到发布页下载安装。`;
    case "error":
      return `检查更新失败：${updater.state.error || "网络不可用"}`;
    default:
      return "应用启动后会自动检查 GitHub 新版本。";
  }
});

const showOpenReleases = computed(
  () => updater.state.status === "error" || updater.state.status === "update-manual",
);

// ===== 服务端口 =====
const portMode = ref<"auto" | "fixed">("auto");
const fixedPortInput = ref("");
const savingPort = ref(false);

async function openDataDir() {
  const api = desktopApi();
  if (api?.openDataDir) await api.openDataDir();
}

function desktopApi() {
  return desktopBridge();
}

async function savePortConfig() {
  const api = desktopApi();
  if (!api?.setPortConfig) return;
  savingPort.value = true;
  try {
    const trimmed = fixedPortInput.value.trim();
    const port = portMode.value === "fixed" && trimmed ? Number(trimmed) : null;
    if (port !== null && (!Number.isInteger(port) || port < 1024 || port > 65535)) {
      notifyError("端口需为 1024–65535 的整数");
      return;
    }
    await api.setPortConfig({ port });
    notifySuccess(port ? `端口已固定为 ${port}，应用即将重启生效` : "已恢复自动分配端口，应用即将重启");
    // 端口在启动时绑定，保存后立即重启应用让配置马上生效
    setTimeout(() => { void api.relaunchApp?.(); }, 900);
  } catch (error) {
    notifyError(`保存失败：${error instanceof Error ? error.message : String(error)}`);
  } finally {
    savingPort.value = false;
  }
}

// ===== 秒传池密钥（默认用安装包内置的分发 Token；可切换管理员 Token 解锁目录搜索） =====
const poolToken = ref<PoolTokenStatus>({ override: false, overridePreview: null, defaultPreview: null });
const poolTokenInput = ref("");
const poolTokenSaving = ref(false);
const poolTokenResetting = ref(false);

async function loadPoolToken() {
  try {
    poolToken.value = await poolApi.tokenStatus();
  } catch {
    /* 未配置秒传池时静默 */
  }
}

async function savePoolToken() {
  const token = poolTokenInput.value.trim();
  if (token.length < 20) {
    notifyError("Token 看起来不对：长度应不少于 20 个字符");
    return;
  }
  poolTokenSaving.value = true;
  try {
    const data = await poolApi.setToken(token);
    poolToken.value = { ...poolToken.value, override: data.override, overridePreview: data.overridePreview };
    poolTokenInput.value = "";
    notifySuccess("秒传池 Token 已切换为自定义 Token");
  } catch (error) {
    notifyError(`保存失败：${error instanceof Error ? error.message : String(error)}`);
  } finally {
    poolTokenSaving.value = false;
  }
}

async function resetPoolToken() {
  if (!(await confirm("重置秒传池密钥？", "恢复为安装包内置的分发 Token，秒传池搜索将不可用。"))) return;
  poolTokenResetting.value = true;
  try {
    await poolApi.resetToken();
    poolToken.value = { ...poolToken.value, override: false, overridePreview: null };
    poolTokenInput.value = "";
    notifySuccess("已重置为默认分发 Token");
  } catch (error) {
    notifyError(`重置失败：${error instanceof Error ? error.message : String(error)}`);
  } finally {
    poolTokenResetting.value = false;
  }
}

onMounted(async () => {
  try {
    const response = await fetch("/api/web-auth/state", { cache: "no-store" });
    const auth = await response.json();
    webAuthEnabled.value = auth.enabled === true;
    if (auth.username) accountUsername.value = auth.username;
    if (webAuthEnabled.value) {
      const proxyResponse = await fetch("/api/web-auth/proxy", { cache: "no-store" });
      if (proxyResponse.ok) proxyUrl.value = (await proxyResponse.json()).url || "";
    }
  } catch { /* desktop mode */ }
  void loadPoolToken();
  const api = desktopApi();
  if (api?.getInfo) {
    try {
      desktopInfo.value = await api.getInfo();
      if (desktopInfo.value?.fixedPort) {
        portMode.value = "fixed";
        fixedPortInput.value = String(desktopInfo.value.fixedPort);
      }
    } catch {
      desktopInfo.value = null;
    }
  }
});
</script>

<template>
  <div class="page">
    <PageHero title="设置" desc="外观、服务端口、数据目录与应用信息。" icon="mdi-cog-outline" group="dashboard" />

    <GlassCard v-if="webAuthEnabled" title="后台账号" desc="修改网页登录账号和密码；不限制密码复杂度。" icon="mdi-shield-account" :hover="false">
      <v-text-field v-model="accountUsername" label="账号" variant="outlined" readonly />
      <v-text-field v-model="accountNewUsername" label="新账号（留空不修改）" variant="outlined" autocomplete="username" />
      <v-text-field v-model="currentPassword" label="当前密码" type="password" variant="outlined" autocomplete="current-password" />
      <v-text-field v-model="newPassword" label="新密码" type="password" variant="outlined" autocomplete="new-password" />
      <div class="d-flex ga-2">
        <v-btn color="primary" :loading="passwordSaving" @click="changeWebPassword">修改账号与密码</v-btn>
        <v-btn variant="outlined" @click="logoutWeb">退出登录</v-btn>
      </div>
    </GlassCard>

    <GlassCard v-if="webAuthEnabled" title="TG / TMDB 代理" desc="填写同一个 HTTP 代理地址，供 Telegram 和 TMDB 出站请求使用。" icon="mdi-web" :hover="false">
      <v-text-field v-model="proxyUrl" label="HTTP 代理地址" placeholder="http://host.docker.internal:7890" variant="outlined" hide-details />
      <p class="muted" style="font-size: 12px; margin: 10px 0">请填写容器可访问的主机和端口；留空则不启用网页代理。保存后立即生效。</p>
      <v-btn color="primary" :loading="proxySaving" @click="saveWebProxy">保存代理</v-btn>
    </GlassCard>

    <div class="section-grid">
      <GlassCard title="外观" desc="液态玻璃支持浅色与深色两种质感。" icon="mdi-palette" :hover="false">
        <div class="theme-options">
          <button
            v-for="option in themeOptions"
            :key="option.value"
            type="button"
            class="theme-option-card"
            :class="{ active: theme.preference === option.value }"
            @click="setTheme(option.value)"
          >
            <span class="theme-option-icon"><v-icon :icon="option.icon" size="20" /></span>
            <span class="theme-option-copy">
              <strong>{{ option.label }}</strong>
              <small>{{ option.desc }}</small>
            </span>
            <v-icon v-if="theme.preference === option.value" icon="mdi-check-circle" size="20" class="theme-check" />
          </button>
        </div>
      </GlassCard>

      <GlassCard title="123 网盘" desc="授权登录后自动获取并刷新 OpenAPI token，转存搬运、投稿归属判断都走官方接口。" icon="mdi-link-variant" :hover="false">
        <div v-if="pan123Authenticated" class="pan-bind">
          <div class="pan-bind-info">
            <span class="pan-bind-avatar">
              <img v-if="pan123Profile?.headImage" :src="pan123Profile.headImage" alt="" />
              <v-icon v-else icon="mdi-account" size="20" />
            </span>
            <span class="pan-bind-copy">
              <strong>{{ pan123Name }}</strong>
              <small>{{ pan123Space || "账号已连接" }}</small>
            </span>
            <span v-if="pan123LoginExpired" class="pan-bind-badge expired">授权已失效</span>
            <span v-else-if="pan123AccessOnly" class="pan-bind-badge">仅访问令牌 · 到期需重新授权</span>
            <span v-else class="pan-bind-badge">已授权</span>
          </div>
          <div class="pan-bind-actions">
            <v-btn v-if="pan123AccessOnly" variant="tonal" size="small" prepend-icon="mdi-key" @click="browserAuthOpen = true; authorizeUrl = ''">
              更新访问令牌
            </v-btn>
            <v-btn variant="tonal" color="primary" size="small" prepend-icon="mdi-refresh" :loading="authorizing" @click="authorizePan123">
              {{ pan123LoginExpired ? "重新授权" : "重新授权" }}
            </v-btn>
            <v-btn variant="tonal" color="error" size="small" prepend-icon="mdi-link-variant-off" :loading="unbinding" @click="unbindPan123">
              解除绑定
            </v-btn>
          </div>
        </div>

        <div v-if="pan123Authenticated && pan123AccessOnly && browserAuthOpen && !authorizeUrl" class="pan-bind-form">
          <v-text-field v-model="callbackInput" label="新的 123 访问令牌" type="password" variant="outlined" autocomplete="off" hide-details />
          <v-btn color="primary" :loading="finishing" @click="importAccessToken">保存访问令牌</v-btn>
        </div>

        <div v-else class="pan-bind-form">
          <v-btn color="primary" :loading="authorizing" prepend-icon="mdi-shield-check-outline" @click="authorizePan123">
            授权登录 123 网盘
          </v-btn>
          <v-btn variant="outlined" :disabled="authorizing" prepend-icon="mdi-key" @click="browserAuthOpen = true">
            手动输入访问令牌
          </v-btn>
          <p class="muted" style="font-size: 11.5px; margin: 2px 0 0">
            点击后会尝试在新标签打开 123 云盘官方授权页；若浏览器阻止弹窗，请点击下方出现的「123 官方授权页」链接。
            只在官方页面输入账号密码；本应用只保存授权后的 token，无需申请开放平台密钥。
          </p>

          <template v-if="browserAuthOpen">
            <v-divider class="my-2" />
            <p class="muted" style="font-size: 12px; margin: 0">
              浏览器模式：<template v-if="authorizeUrl">在新标签打开 <a :href="authorizeUrl" target="_blank" rel="noopener">123 官方授权页</a>。完成授权后，复制最终页面地址栏的完整 URL（含 # 后面的内容），回到这里点「读取剪贴板并完成授权」。</template>
              <template v-else>若已有 123 访问令牌，可直接在下方粘贴并保存。</template>
              浏览器禁止本页直接读取第三方标签的地址，因此这一步需要你复制。也可以手动粘贴地址、刷新令牌或访问令牌；仅访问令牌到期后无法自动续期。
            </p>
            <v-text-field
              v-model="callbackInput"
              label="回调地址 / 刷新令牌 / 访问令牌"
              type="password"
              placeholder="完整回调地址，或刷新令牌 / 访问令牌"
              variant="outlined"
              density="comfortable"
              hide-details
            />
            <div class="d-flex ga-2 flex-wrap">
              <v-btn v-if="authorizeUrl" color="primary" :loading="readingCallback || finishing" prepend-icon="mdi-content-paste" @click="pasteAndFinishBrowserAuth">读取剪贴板并完成授权</v-btn>
              <v-btn v-else color="primary" :loading="finishing" prepend-icon="mdi-content-save" @click="importAccessToken">保存访问令牌</v-btn>
              <v-btn variant="outlined" :loading="finishing" prepend-icon="mdi-check" @click="finishBrowserAuth">使用输入内容完成授权</v-btn>
            </div>
          </template>
        </div>
      </GlassCard>

      <GlassCard title="秒传池密钥" desc="默认使用安装包内置的分发 Token：只加速搬运，不能搜索共享池目录。切换为管理员 Token 可解锁「秒传池」页的目录搜索；重置即恢复默认。" icon="mdi-key-variant" :hover="false">
        <FormField label="当前生效">
          <code class="settings-path">
            {{ poolToken.override ? `自定义 Token（${poolToken.overridePreview}）` : `默认分发 Token（${poolToken.defaultPreview || "未配置"}）` }}
          </code>
        </FormField>
        <FormField hint="仅本机生效、保存在本地数据目录；管理员 Token 可解锁秒传池搜索，分发出去的安装包始终是默认分发 Token。">
          <div class="port-row">
            <v-text-field
              v-model="poolTokenInput"
              label="新的秒传池 Token"
              placeholder="粘贴管理员 Token（不少于 20 个字符）"
              type="password"
              variant="outlined"
              density="compact"
              hide-details
              clearable
              class="port-input"
            />
            <v-btn color="primary" :loading="poolTokenSaving" prepend-icon="mdi-key-change" @click="savePoolToken">保存并切换</v-btn>
            <v-btn variant="outlined" :loading="poolTokenResetting" :disabled="!poolToken.override" prepend-icon="mdi-restore" @click="resetPoolToken">重置为默认</v-btn>
          </div>
        </FormField>
      </GlassCard>

      <GlassCard title="服务端口" desc="后端默认只监听本机并自动选择空闲端口。" icon="mdi-lan" :hover="false">
        <FormField label="当前端口">
          <code class="settings-path">{{ desktopInfo ? `${desktopInfo.port}${desktopInfo.fixedPort ? "（固定）" : "（自动分配）"}` : "仅桌面应用可用" }}</code>
        </FormField>
        <FormField hint="端口冲突或需要端口转发时，可固定为指定端口；保存后应用自动重启并生效。">
          <div class="port-row">
            <v-btn-toggle v-model="portMode" mandatory density="compact" class="port-toggle">
              <v-btn value="auto">自动</v-btn>
              <v-btn value="fixed">固定端口</v-btn>
            </v-btn-toggle>
            <v-text-field
              v-if="portMode === 'fixed'"
              v-model="fixedPortInput"
              type="number"
              density="compact"
              hide-details
              placeholder="1024–65535"
              class="port-input"
            />
            <v-btn
              variant="tonal"
              size="small"
              :loading="savingPort"
              prepend-icon="mdi-content-save"
              :disabled="!desktopInfo?.isDesktop"
              @click="savePortConfig"
            >
              保存
            </v-btn>
          </div>
        </FormField>
      </GlassCard>

      <GlassCard title="数据目录" desc="配置、会话与任务数据都保存在本地。" icon="mdi-database-outline" :hover="false">
        <FormField label="数据目录">
          <code class="settings-path">{{ desktopInfo?.dataDir || "浏览器模式：数据由后端 DATA_DIR 决定" }}</code>
        </FormField>
        <FormField hint="包含 cloud123.db 数据库与应用配置。">
          <v-btn
            v-if="desktopInfo?.isDesktop"
            variant="tonal"
            size="small"
            prepend-icon="mdi-folder-open-outline"
            @click="openDataDir"
          >
            打开数据文件夹
          </v-btn>
          <span v-else class="muted" style="font-size: 12px">桌面应用内可用一键打开</span>
        </FormField>
      </GlassCard>

      <GlassCard
        v-if="updater.available"
        title="软件更新"
        desc="自动检测 GitHub 新版本；下载后重启即可升级，配置与数据不受影响。"
        icon="mdi-cellphone-arrow-down"
        :hover="false"
      >
        <div class="update-row">
          <div class="update-copy">
            <strong>当前版本 {{ appVersion || "未知" }}</strong>
            <small>{{ updateStatusText }}</small>
          </div>
          <div class="update-actions">
            <v-btn
              v-if="updater.state.status === 'downloaded'"
              color="primary"
              prepend-icon="mdi-restart"
              @click="updater.install()"
            >
              重启并安装
            </v-btn>
            <v-btn
              v-if="showOpenReleases"
              :color="updater.state.status === 'update-manual' ? 'primary' : undefined"
              :variant="updater.state.status === 'update-manual' ? 'flat' : 'text'"
              href="https://github.com/weige146/123Cloud/releases/latest"
              target="_blank"
              prepend-icon="mdi-open-in-new"
            >
              打开发布页
            </v-btn>
            <v-btn
              v-if="updater.state.status !== 'downloaded' && updater.state.status !== 'update-manual'"
              variant="tonal"
              prepend-icon="mdi-refresh"
              :loading="updater.state.status === 'checking' || updater.state.status === 'downloading'"
              @click="updater.check()"
            >
              检查更新
            </v-btn>
          </div>
        </div>
      </GlassCard>

      <GlassCard title="关于" desc="123Cloud — Telegram 投稿与 115 协作工作台。" icon="mdi-information-outline" :hover="false">
        <div class="kv-grid">
          <div class="kv-tile">
            <div class="kv-tile-label">应用版本</div>
            <div class="kv-tile-value">{{ desktopInfo?.versions?.app || "1.0.0（浏览器模式）" }}</div>
          </div>
          <div class="kv-tile">
            <div class="kv-tile-label">后端服务</div>
            <div class="kv-tile-value">{{ backendVersion }}</div>
          </div>
          <div class="kv-tile">
            <div class="kv-tile-label">运行平台</div>
            <div class="kv-tile-value">{{ desktopInfo?.platform || "browser" }}</div>
          </div>
          <div v-if="desktopInfo?.versions?.electron" class="kv-tile">
            <div class="kv-tile-label">Electron</div>
            <div class="kv-tile-value">{{ desktopInfo.versions.electron }}</div>
          </div>
        </div>
      </GlassCard>
    </div>
  </div>
</template>

<style scoped>
.theme-options { display: flex; flex-direction: column; gap: 10px; }

.theme-option-card {
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 13px 14px;
  border-radius: var(--radius-control);
  border: 1px solid var(--border);
  background: var(--surface-subtle);
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color var(--transition), background var(--transition), box-shadow var(--transition);
}
.theme-option-card:hover { border-color: var(--glass-border-1); background: var(--bg-hover); }
.theme-option-card.active {
  border-color: rgba(124, 92, 255, 0.5);
  background: linear-gradient(130deg, rgba(124, 92, 255, 0.18), rgba(76, 201, 240, 0.08));
  box-shadow: 0 0 0 3px rgba(124, 92, 255, 0.12), inset 0 1px 0 var(--glass-highlight);
}

.theme-option-icon {
  width: 36px; height: 36px;
  flex: 0 0 36px;
  border-radius: 11px;
  display: grid;
  place-items: center;
  background: var(--accent-soft);
  color: var(--accent-2);
}
.theme-option-card.active .theme-option-icon {
  background: var(--grad-accent);
  color: #fff;
  box-shadow: 0 6px 14px rgba(124, 92, 255, 0.3);
}

.theme-option-copy { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.theme-option-copy strong { font-size: 13px; font-weight: 640; color: var(--text-primary); }
.theme-option-copy small { color: var(--text-muted); font-size: 11.5px; }
.theme-check { color: var(--accent-2); }

.settings-path {
  display: block;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--surface-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 9px 11px;
  word-break: break-all;
}

.pan-bind { display: flex; flex-direction: column; gap: 14px; }
.pan-bind-info {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: var(--radius-control);
  border: 1px solid var(--border);
  background: var(--surface-subtle);
}
.pan-bind-avatar {
  width: 38px; height: 38px;
  flex: 0 0 38px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  overflow: hidden;
  background: var(--accent-soft);
  color: var(--accent-2);
}
.pan-bind-avatar img { width: 100%; height: 100%; object-fit: cover; }
.pan-bind-copy { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.pan-bind-copy strong {
  font-size: 13px; font-weight: 640; color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.pan-bind-copy small { color: var(--text-muted); font-size: 11.5px; }
.pan-bind-badge {
  flex: 0 0 auto;
  font-size: 11px; font-weight: 600;
  color: var(--success, #2ecc71);
  background: rgba(46, 204, 113, 0.12);
  border: 1px solid rgba(46, 204, 113, 0.3);
  border-radius: var(--radius-pill);
  padding: 3px 10px;
}
.pan-bind-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.pan-bind-form { display: flex; flex-direction: column; gap: 12px; }
.pan-bind-badge.expired {
  color: var(--warning, #f39c12);
  background: rgba(243, 156, 18, 0.12);
  border-color: rgba(243, 156, 18, 0.35);
}

.port-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.port-toggle { background: var(--surface-subtle); border-radius: var(--radius-pill); }
.port-input { width: 150px; }

.update-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
}
.update-copy { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.update-copy strong { font-size: 13px; font-weight: 640; color: var(--text-primary); }
.update-copy small { color: var(--text-muted); font-size: 11.5px; }
.update-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
</style>
