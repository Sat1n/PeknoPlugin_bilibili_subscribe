# bilibili_subscribe

## 中文

`bilibili_subscribe` 是一个面向 Pekno / Iris Hub 的第三方插件，用于获取用户关注的 Bilibili 视频动态。

这个插件由 RSSHub 驱动，主要同步 RSSHub 路由：

```text
/bilibili/followings/video/:uid
```

插件需要用户配置：

- `uid`：Bilibili 用户 UID
- `rsshub_base_url`：RSSHub 地址，例如 `http://127.0.0.1:1200`
- `SESSDATA`：Bilibili 登录凭据，在 Pekno 的插件凭据设置中填写

### 安装方式

不要使用 `git clone`。请直接在 GitHub 页面下载代码仓库：

1. 打开本仓库 GitHub 页面。
2. 点击 `Code`。
3. 选择 `Download ZIP`。
4. 不需要解压下载得到的 ZIP 文件。
5. 在 Pekno 的插件页面上传这个 ZIP 压缩包并安装。

## English

`bilibili_subscribe` is a third-party plugin for Pekno / Iris Hub. It syncs Bilibili video updates from the accounts followed by a user.

This plugin is powered by RSSHub and uses the RSSHub route:

```text
/bilibili/followings/video/:uid
```

Required user configuration:

- `uid`: Bilibili user UID
- `rsshub_base_url`: RSSHub base URL, for example `http://127.0.0.1:1200`
- `SESSDATA`: Bilibili login credential, configured in Pekno plugin credentials

### Installation

Do not use `git clone`. Download the repository directly from GitHub:

1. Open the GitHub repository page.
2. Click `Code`.
3. Select `Download ZIP`.
4. Do not unzip the downloaded ZIP file.
5. Upload the ZIP package directly on the Pekno plugin page to install it.

## License

MIT
