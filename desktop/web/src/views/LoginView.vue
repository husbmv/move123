<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();
const username = ref("admin");
const password = ref("");
const error = ref("");
const loading = ref(false);

async function login() {
  loading.value = true;
  error.value = "";
  try {
    const response = await fetch("/api/web-auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username: username.value, password: password.value }),
    });
    if (!response.ok) throw new Error((await response.json()).detail || "登录失败");
    const next = typeof route.query.next === "string" && route.query.next.startsWith("/admin/") && !route.query.next.startsWith("//")
      ? route.query.next : "/admin/console";
    await router.replace(next);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "登录失败";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-wrap">
    <v-card class="login-card" elevation="8">
      <v-card-title>123Cloud 管理后台</v-card-title>
      <v-card-text>
        <v-form @submit.prevent="login">
          <v-text-field v-model="username" label="账号" autocomplete="username" variant="outlined" />
          <v-text-field v-model="password" label="密码" type="password" autocomplete="current-password" variant="outlined" />
          <v-alert v-if="error" type="error" class="mb-4">{{ error }}</v-alert>
          <v-btn type="submit" color="primary" block :loading="loading">登录</v-btn>
        </v-form>
      </v-card-text>
    </v-card>
  </div>
</template>

<style scoped>
.login-wrap { min-height: 100vh; display: grid; place-items: center; padding: 20px; }
.login-card { width: min(100%, 400px); padding: 12px; }
</style>
