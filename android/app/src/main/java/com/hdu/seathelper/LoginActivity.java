package com.hdu.seathelper;

import android.app.Activity;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Bundle;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

/** Passwords are entered only into the university's official HTTPS page. */
public final class LoginActivity extends Activity {
    static final String LIBRARY_ORIGIN = "https://hdu.huitu.zhishulib.com";
    static final String LOGIN_URL = LIBRARY_ORIGIN + "/Seat/Index";
    private WebView web;
    private TextView address;
    private TextView instruction;
    private Button complete;
    private volatile boolean verifying;
    private boolean destroyed;

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Ui.PAPER);
        setContentView(root);
        Ui.insets(this, root);
        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setPadding(Ui.dp(this, 8), Ui.dp(this, 4), Ui.dp(this, 8), Ui.dp(this, 4));
        Button back = new Button(this);
        back.setText("返回");
        back.setOnClickListener(view -> finish());
        toolbar.addView(back, new LinearLayout.LayoutParams(Ui.dp(this, 72), -2));
        LinearLayout title = new LinearLayout(this);
        title.setOrientation(LinearLayout.VERTICAL);
        TextView name = new TextView(this);
        name.setText("学校账号登录");
        name.setTextSize(17);
        name.setTextColor(Ui.INK);
        title.addView(name);
        address = new TextView(this);
        address.setText("hdu.huitu.zhishulib.com");
        address.setTextSize(11);
        address.setTextColor(Ui.GREEN);
        address.setSingleLine(true);
        address.setEllipsize(TextUtils.TruncateAt.MIDDLE);
        title.addView(address);
        toolbar.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
        complete = new Button(this);
        complete.setText("完成登录");
        complete.setTextSize(13);
        complete.setOnClickListener(view -> verifySession(true));
        toolbar.addView(complete, new LinearLayout.LayoutParams(Ui.dp(this, 104), -2));
        root.addView(toolbar);
        instruction = new TextView(this);
        instruction.setText("在学校页面输入账号密码；验证通过后会自动返回。");
        instruction.setTextColor(Ui.INK);
        instruction.setTextSize(12);
        instruction.setPadding(Ui.dp(this, 16), 0, Ui.dp(this, 16), Ui.dp(this, 8));
        root.addView(instruction);
        web = new WebView(this);
        root.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportMultipleWindows(false);
        settings.setSaveFormData(false);
        settings.setSavePassword(false);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true);
        // This WebView intentionally has NO addJavascriptInterface bridge.
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (allowed(request.getUrl())) return false;
                Toast.makeText(LoginActivity.this, "登录仅支持学校和图书馆官方 HTTPS 页面", Toast.LENGTH_SHORT).show();
                return true;
            }
            @Override public void onPageStarted(WebView view, String url, Bitmap icon) {
                Uri uri = Uri.parse(url);
                if (!allowed(uri)) {
                    view.stopLoading();
                    instruction.setText("已阻止非官方登录页面，请返回后重试。");
                    return;
                }
                address.setText(uri.getHost());
            }
            @Override public void onPageFinished(WebView view, String url) {
                Uri uri = Uri.parse(url);
                if (allowed(uri) && "hdu.huitu.zhishulib.com".equals(uri.getHost())) verifySession(false);
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, android.webkit.WebResourceError error) {
                if (request.isForMainFrame()) {
                    instruction.setText("无法连接学校登录服务，请检查网络后点击“重新加载”。");
                    complete.setText("重新加载");
                    complete.setOnClickListener(button -> {
                        complete.setText("完成登录");
                        complete.setOnClickListener(again -> verifySession(true));
                        web.loadUrl(LOGIN_URL);
                    });
                }
            }
        });
        web.loadUrl(LOGIN_URL);
    }

    static boolean allowed(Uri uri) {
        if (uri == null || !"https".equals(uri.getScheme()) || uri.getUserInfo() != null || (uri.getPort() != -1 && uri.getPort() != 443)) return false;
        String host = uri.getHost();
        return host != null && (host.equals("hdu.huitu.zhishulib.com") || host.equals("hdu.edu.cn") || host.endsWith(".hdu.edu.cn"));
    }

    private void verifySession(boolean manual) {
        if (verifying || destroyed) return;
        String cookies = CookieManager.getInstance().getCookie(LIBRARY_ORIGIN);
        if (cookies == null || cookies.isEmpty()) {
            if (manual) Toast.makeText(this, "请先完成学校账号登录及页面验证", Toast.LENGTH_SHORT).show();
            return;
        }
        verifying = true;
        complete.setEnabled(false);
        instruction.setText("正在验证图书馆登录状态…");
        RuntimeHost.IO.execute(() -> {
            boolean authenticated = false;
            try {
                authenticated = RuntimeHost.module().callAttr("set_session", cookies).toBoolean();
            } catch (Exception ignored) {
                // A rejected session or upstream failure must never expose its cookies.
            }
            boolean success = authenticated;
            runOnUiThread(() -> {
                if (destroyed) return;
                verifying = false;
                complete.setEnabled(true);
                if (success) {
                    CookieManager.getInstance().flush();
                    setResult(RESULT_OK);
                    finish();
                } else {
                    instruction.setText("请完成账号密码登录和学校验证，再点击“完成登录”；网络异常时可重试。");
                    if (manual) Toast.makeText(this, "登录尚未验证成功，请完成官方页面操作后重试", Toast.LENGTH_LONG).show();
                }
            });
        });
    }

    @Override public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack(); else finish();
    }

    @Override protected void onDestroy() {
        destroyed = true;
        if (web != null) {
            web.stopLoading();
            ((android.view.ViewGroup) web.getParent()).removeView(web);
            web.destroy();
        }
        super.onDestroy();
    }
}
