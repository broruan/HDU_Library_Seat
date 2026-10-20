package com.hdu.seathelper;

import android.content.Context;
import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.io.File;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** The only bridge into the shared Python implementation; never log credentials. */
final class RuntimeHost {
    static final ExecutorService IO = Executors.newCachedThreadPool();
    static final ExecutorService LIFECYCLE = Executors.newSingleThreadExecutor();
    private static PyObject module;
    private static String url;

    private RuntimeHost() { }

    static synchronized String start(Context context) {
        if (url != null) return url;
        if (!Python.isStarted()) Python.start(new AndroidPlatform(context.getApplicationContext()));
        module = Python.getInstance().getModule("hdu_seat.android_runtime");
        url = module.callAttr("start", new File(context.getFilesDir(), "config.json").getAbsolutePath()).toString();
        return url;
    }

    static synchronized PyObject module() {
        if (module == null || url == null) throw new IllegalStateException("本地服务尚未启动");
        return module;
    }

    static synchronized void stop() {
        if (module != null && url != null) module.callAttr("stop");
        url = null;
    }
}
