package com.hdu.seathelper;

import java.net.URI;
import java.util.HashSet;
import java.util.Set;

/** URL boundary shared by the native login WebView and its session reader. */
final class LoginNavigation {
    static final String LIBRARY_ORIGIN = "https://hdu.huitu.zhishulib.com";
    static final String LOGIN_URL = LIBRARY_ORIGIN + "/#!/Seat/Index/index";
    static final String SESSION_URL = LIBRARY_ORIGIN + "/Seat/Index/searchSeats";

    interface CookieReader { String get(String url); }

    private LoginNavigation() { }

    static String sessionCookies(CookieReader reader) {
        // Ask for the same URL the booking client uses, so CookieManager also
        // includes cookies scoped to /Seat. Preserve that header's ordering.
        String primary = reader.get(SESSION_URL);
        String root = reader.get(LIBRARY_ORIGIN + "/");
        StringBuilder cookies = new StringBuilder(primary == null ? "" : primary.trim());
        Set<String> names = new HashSet<>();
        for (String item : cookies.toString().split(";")) {
            int separator = item.indexOf('=');
            if (separator > 0) names.add(item.substring(0, separator).trim());
        }
        if (root != null) for (String item : root.split(";")) {
            int separator = item.indexOf('=');
            if (separator <= 0 || !names.add(item.substring(0, separator).trim())) continue;
            if (cookies.length() > 0) cookies.append("; ");
            cookies.append(item.trim());
        }
        return cookies.toString();
    }

    static String appUrlForTopLevel(String url) {
        try {
            URI uri = URI.create(url);
            if (!"https".equals(uri.getScheme()) || !"hdu.huitu.zhishulib.com".equals(uri.getHost())
                    || uri.getUserInfo() != null || (uri.getPort() != -1 && uri.getPort() != 443)) return null;
            String path = uri.getPath();
            if ("/Seat/Index".equals(path) || "/Seat/Index/".equals(path) || "/Seat/Index/index".equals(path)) {
                return LOGIN_URL;
            }
        } catch (IllegalArgumentException ignored) { }
        return null;
    }
}
