package com.hdu.seathelper;

import android.Manifest;
import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import java.io.ByteArrayInputStream;

public final class MainActivity extends Activity {
    private static final int LOGIN_REQUEST = 41;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private FrameLayout root;
    private WebView web;
    private LinearLayout status;
    private TextView message;
    private Button retry;
    private SeatService service;
    private String localPrefix;
    private String loadedPrefix;
    private boolean bound;
    private boolean destroyed;

    private final ServiceConnection connection = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder binder) {
            service = ((SeatService.LocalBinder) binder).service();
        }
        @Override public void onServiceDisconnected(ComponentName name) {
            service = null;
            loadedPrefix = null;
            showStatus("本地服务已停止", true);
        }
    };

    private final Runnable checkReady = new Runnable() {
        @Override public void run() {
            if (destroyed) return;
            if (service != null) {
                if (service.stopped()) {
                    loadedPrefix = null;
                    showStatus("服务已停止，预约任务也已结束", true);
                } else if (service.error() != null) {
                    showStatus(service.error(), true);
                } else if (service.url() != null && !service.url().equals(loadedPrefix)) {
                    localPrefix = service.url();
                    loadedPrefix = localPrefix;
                    web.loadUrl(localPrefix + "?platform=android");
                }
            }
            handler.postDelayed(this, 500);
        }
    };

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        root = new FrameLayout(this);
        root.setBackgroundColor(Ui.PAPER);
        setContentView(root);
        Ui.insets(this, root);
        web = new WebView(this);
        web.setBackgroundColor(Ui.PAPER);
        root.addView(web, new FrameLayout.LayoutParams(-1, -1));
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportMultipleWindows(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        web.addJavascriptInterface(new DashboardBridge(), "HduAndroid");
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return !isLocal(request.getUrl());
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                if (isLocal(request.getUrl())) return null;
                return new WebResourceResponse("text/plain", "UTF-8", 403, "Forbidden", java.util.Collections.emptyMap(), new ByteArrayInputStream(new byte[0]));
            }
            @Override public void onPageStarted(WebView view, String url, Bitmap icon) {
                if (!isLocal(Uri.parse(url))) view.stopLoading();
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (isLocal(Uri.parse(url))) status.setVisibility(View.GONE);
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, android.webkit.WebResourceError error) {
                if (request.isForMainFrame()) showStatus("无法打开本地面板，请重新启动服务", true);
            }
        });
        createStatus();
        startLocalService();
        handler.post(checkReady);
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] { Manifest.permission.POST_NOTIFICATIONS }, 42);
        }
    }

    private boolean isLocal(Uri uri) {
        if (localPrefix == null || uri == null) return false;
        Uri expected = Uri.parse(localPrefix);
        return "http".equals(uri.getScheme()) && "127.0.0.1".equals(uri.getHost())
                && uri.getPort() == expected.getPort() && uri.getUserInfo() == null
                && uri.getPath() != null && uri.getPath().startsWith(expected.getPath());
    }

    private void createStatus() {
        status = new LinearLayout(this);
        status.setOrientation(LinearLayout.VERTICAL);
        status.setGravity(Gravity.CENTER);
        status.setPadding(Ui.dp(this, 24), Ui.dp(this, 24), Ui.dp(this, 24), Ui.dp(this, 24));
        status.setBackgroundColor(Ui.PAPER);
        message = new TextView(this);
        message.setTextSize(18);
        message.setTextColor(Ui.INK);
        message.setGravity(Gravity.CENTER);
        status.addView(message);
        retry = new Button(this);
        retry.setText("重新启动");
        retry.setOnClickListener(view -> {
            if (bound) { unbindService(connection); bound = false; }
            stopService(new Intent(this, SeatService.class));
            service = null;
            loadedPrefix = null;
            startLocalService();
        });
        status.addView(retry);
        root.addView(status, new FrameLayout.LayoutParams(-1, -1));
        showStatus("正在打开杭电座位助手…", false);
    }

    private void showStatus(String text, boolean canRetry) {
        message.setText(text);
        retry.setVisibility(canRetry ? View.VISIBLE : View.GONE);
        status.setVisibility(View.VISIBLE);
    }

    private void startLocalService() {
        showStatus("正在打开杭电座位助手…", false);
        Intent intent = new Intent(this, SeatService.class);
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent); else startService(intent);
        bound = bindService(intent, connection, BIND_AUTO_CREATE);
    }

    private void sessionChanged() {
        if (!destroyed && web != null && isLocal(Uri.parse(web.getUrl() == null ? "" : web.getUrl()))) {
            web.evaluateJavascript("window.hduAndroidSessionChanged && window.hduAndroidSessionChanged()", null);
        }
    }

    private final class DashboardBridge {
        @JavascriptInterface public void signIn() {
            runOnUiThread(() -> {
                if (!destroyed && isLocal(Uri.parse(web.getUrl() == null ? "" : web.getUrl()))) {
                    startActivityForResult(new Intent(MainActivity.this, LoginActivity.class), LOGIN_REQUEST);
                }
            });
        }
        @JavascriptInterface public void signOut() {
            RuntimeHost.IO.execute(() -> {
                try {
                    RuntimeHost.module().callAttr("clear_session");
                    runOnUiThread(() -> CookieManager.getInstance().removeAllCookies(done -> {
                        CookieManager.getInstance().flush();
                        sessionChanged();
                    }));
                } catch (Exception ignored) {
                    runOnUiThread(() -> Toast.makeText(MainActivity.this, "退出登录失败，请重试", Toast.LENGTH_SHORT).show());
                }
            });
        }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == LOGIN_REQUEST) sessionChanged();
    }

    @Override public void onBackPressed() {
        // Going home keeps an explicitly started scheduled task running in its service.
        moveTaskToBack(true);
    }

    @Override protected void onDestroy() {
        destroyed = true;
        handler.removeCallbacks(checkReady);
        if (bound) unbindService(connection);
        if (web != null) {
            web.removeJavascriptInterface("HduAndroid");
            root.removeView(web);
            web.destroy();
        }
        super.onDestroy();
    }
}
