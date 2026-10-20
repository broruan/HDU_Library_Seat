package com.hdu.seathelper;

import android.app.Activity;
import android.graphics.Color;
import android.os.Build;
import android.view.View;
import android.view.WindowInsets;

final class Ui {
    static final int PAPER = Color.rgb(246, 244, 238);
    static final int GREEN = Color.rgb(24, 119, 91);
    static final int INK = Color.rgb(30, 45, 39);

    private Ui() { }

    static int dp(Activity activity, int value) {
        return Math.round(value * activity.getResources().getDisplayMetrics().density);
    }

    static void insets(Activity activity, View root) {
        activity.getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        if (Build.VERSION.SDK_INT >= 30) {
            activity.getWindow().setDecorFitsSystemWindows(false);
            root.setOnApplyWindowInsetsListener((view, insets) -> {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
                return insets;
            });
        } else {
            root.setFitsSystemWindows(true);
        }
    }
}
