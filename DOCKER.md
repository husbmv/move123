# Docker 网页版

完整的功能介绍与逐步操作请看 [Docker 网页版使用手册](DOCKER_GUIDE.md)。

本仓库的 Docker 变体使用原有 FastAPI + Vue 管理页，不启动 Electron。访问地址为 **http://localhost:12315/admin/**。首次登录账号 `admin`、密码 `password`；登录后到「设置 → 后台账号」修改账号和密码，密码不做复杂度限制（不能为空）。账号哈希与会话保存在 `./data/cloud123.db`，容器重建仍保留。

```sh
docker compose up -d --build
docker compose logs -f cloud123
```

登录后在「设置 → TG / TMDB 代理」填写同一个 HTTP 代理地址并保存，配置会持久化，立即用于 TG 与 TMDB，无需编辑环境文件。Docker Desktop 的宿主机代理地址可用 host.docker.internal，但代理程序必须监听容器可达的地址，不能只监听宿主机的 127.0.0.1。代理支持 HTTP 或 SOCKS5 URL，例如 http://host.docker.internal:7890。若代理需要认证，在 URL 中加入用户名和密码并对特殊字符做 URL 编码。未填写时不会使用专用代理。也可通过 TG_PROXY_URL、TMDB_PROXY_URL 环境变量分别设置；网页保存的代理会覆盖它们。

123 云盘授权会尝试在新标签打开官方授权页；若浏览器阻止弹窗，可点击设置页显示的「123 官方授权页」手动打开。完成后复制最终页面地址栏的完整 URL（含 # 后内容），回设置页点「读取剪贴板并完成授权」；也可手动粘贴回调地址或刷新令牌。桌面专有的本地播放器、原生文件选择器和自动更新在 Docker 中不可用；浏览器上传影库文件仍可使用。应用存储网盘授权、Cookie 和 TG Session，建议仅在可信局域网或经 HTTPS 反向代理访问，**首次登录后立即改密**。默认 Compose 将端口绑定到所有网卡；如果只在本机访问，把端口映射改为 `127.0.0.1:12315:12315`。

停止：`docker compose down`；更新：`git pull && docker compose up -d --build`。不要使用 `down -v` 或删除 `./data`，否则配置会丢失。
