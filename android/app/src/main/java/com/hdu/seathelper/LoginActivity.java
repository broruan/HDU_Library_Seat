package com.hdu.seathelper;

import android.app.Activity;
import android.annotation.SuppressLint;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Bundle;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONObject;

/** Passwords are entered only into the university's official HTTPS page. */
public final class LoginActivity extends Activity {
    static final String LIBRARY_ORIGIN = LoginNavigation.LIBRARY_ORIGIN;
    static final String LOGIN_URL = LoginNavigation.LOGIN_URL;
    private WebView web;
    private TextView address;
    private TextView instruction;
    private Button complete;
    private ProgressBar progress;
    private volatile boolean verifying;
    private boolean destroyed;
    private boolean pageFailed;

    @SuppressLint("SetJavaScriptEnabled") // Official CAS requires JavaScript; no native bridge is exposed here.
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
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(100);
        root.addView(progress, new LinearLayout.LayoutParams(-1, Ui.dp(this, 3)));
        web = new WebView(this);
        root.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportMultipleWindows(false);
        settings.setSaveFormData(false);
        settings.setSavePassword(false);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true);
        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onProgressChanged(WebView view, int value) {
                progress.setProgress(value);
                progress.setVisibility(value < 100 && !pageFailed ? View.VISIBLE : View.GONE);
            }
        });
        // This WebView intentionally has NO addJavascriptInterface bridge.
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (allowed(request.getUrl())) {
                    if (request.isForMainFrame() && recoverController(view, request.getUrl().toString())) return true;
                    return false;
                }
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
                if (recoverController(view, url)) return;
                pageFailed = false;
                progress.setVisibility(View.VISIBLE);
                complete.setText("完成登录");
                complete.setOnClickListener(button -> verifySession(true));
                if (!verifying) instruction.setText("正在连接学校登录服务，请等待页面加载…");
                address.setText(uri.getHost());
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (!url.equals(view.getUrl())) return;
                Uri uri = Uri.parse(url);
                if (!allowed(uri) || pageFailed || recoverController(view, url)) return;
                progress.setVisibility(View.GONE);
                if (!verifying) instruction.setText("在学校页面输入账号密码；已登录时可点击“完成登录”。");
                if ("hdu.huitu.zhishulib.com".equals(uri.getHost())) verifySession(false);
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, android.webkit.WebResourceError error) {
                if (request.isForMainFrame()) {
                    pageFailed = true;
                    progress.setVisibility(View.GONE);
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

    private boolean recoverController(WebView view, String url) {
        String appUrl = LoginNavigation.appUrlForTopLevel(url);
        if (appUrl == null) return false;
        // CAS can return a controller URL. Its HTML is only 'Seat Index'; the
        // official React app must be bootstrapped from / with a hash route.
        view.loadUrl(appUrl);
        return true;
    }

    static boolean allowed(Uri uri) {
        if (uri == null || !"https".equals(uri.getScheme()) || uri.getUserInfo() != null || (uri.getPort() != -1 && uri.getPort() != 443)) return false;
        String host = uri.getHost();
        return host != null && (host.equals("hdu.huitu.zhishulib.com") || host.equals("hdu.edu.cn") || host.endsWith(".hdu.edu.cn"));
    }

    private void verifySession(boolean manual) {
        if (verifying || destroyed) return;
        String cookies = LoginNavigation.sessionCookies(url -> CookieManager.getInstance().getCookie(url));
        if (cookies == null || cookies.isEmpty()) {
            if (manual) Toast.makeText(this, "请先完成学校账号登录及页面验证", Toast.LENGTH_SHORT).show();
            return;
        }
        verifying = true;
        String userAgent = web.getSettings().getUserAgentString();
        complete.setEnabled(false);
        instruction.setText("正在验证图书馆登录状态…");
        RuntimeHost.IO.execute(() -> {
            boolean authenticated = false;
            String status = "upstream_error";
            String resultMessage = "登录验证服务暂不可用，请返回面板后重新打开登录。";
            try {
                JSONObject result = new JSONObject(RuntimeHost.module().callAttr("verify_session_json", cookies, userAgent).toString());
                authenticated = result.optBoolean("authenticated");
                status = result.optString("status", "upstream_error");
                resultMessage = result.optString("message", resultMessage);
            } catch (Exception ignored) {
                // A rejected session or upstream failure must never expose its cookies.
            }
            boolean success = authenticated;
            String finalStatus = status;
            String finalMessage = resultMessage;
            runOnUiThread(() -> {
                if (destroyed) return;
                verifying = false;
                complete.setEnabled(true);
                if (success) {
                    CookieManager.getInstance().flush();
                    setResult(RESULT_OK);
                    finish();
                } else {
                    // A network or parsing failure is not evidence of logout.
                    // Keep the current official page and its entered account.
                    if (manual || !"login_required".equals(finalStatus)) instruction.setText(finalMessage);
                    else instruction.setText("在学校页面输入账号密码；已登录时可点击“完成登录”。");
                    if (manual) Toast.makeText(this, finalMessage, Toast.LENGTH_LONG).show();
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
