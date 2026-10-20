package com.hdu.seathelper;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.os.Binder;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

/** Keeps a user-started local server and its reservation task alive with a visible stop action. */
public final class SeatService extends Service {
    static final String ACTION_STOP = "com.hdu.seathelper.STOP";
    private static final String CHANNEL = "seat_service";
    private static final String RESULTS = "seat_results";
    private static final int NOTIFICATION_ID = 1;
    private final LocalBinder binder = new LocalBinder();
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ScheduledExecutorService monitor = Executors.newSingleThreadScheduledExecutor();
    private volatile String url;
    private volatile String error;
    private volatile boolean destroyed;
    private PowerManager.WakeLock wakeLock;
    private long lastWakeRenewal;
    private String previousMessage = "正在启动本地面板";
    private String previousSuccess;

    public final class LocalBinder extends Binder {
        SeatService service() { return SeatService.this; }
    }

    String url() { return url; }
    String error() { return error; }
    boolean stopped() { return destroyed; }

    @Override public void onCreate() {
        super.onCreate();
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(new NotificationChannel(CHANNEL, "预约任务与本地面板", NotificationManager.IMPORTANCE_LOW));
            manager.createNotificationChannel(new NotificationChannel(RESULTS, "预约结果", NotificationManager.IMPORTANCE_DEFAULT));
        }
        Notification notification = notification(previousMessage);
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }
        PowerManager power = getSystemService(PowerManager.class);
        wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "hdu-seat:reservation");
        wakeLock.setReferenceCounted(false);
        RuntimeHost.LIFECYCLE.execute(() -> {
            try {
                String startedUrl = RuntimeHost.start(this);
                if (destroyed) return;
                url = startedUrl;
                monitor.scheduleWithFixedDelay(this::refreshStatus, 0, 2, TimeUnit.SECONDS);
            } catch (Exception ignored) {
                error = "本地服务启动失败，请关闭后重新打开应用";
                updateNotification(error);
            }
        });
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            shutdown();
            stopSelf();
        }
        return START_NOT_STICKY;
    }

    private Notification.Builder builder(String channel) {
        return Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, channel) : new Notification.Builder(this);
    }

    private PendingIntent openIntent() {
        return PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    private Notification notification(String message) {
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, SeatService.class).setAction(ACTION_STOP), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return builder(CHANNEL)
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle("杭电座位助手")
                .setContentText(message)
                .setContentIntent(openIntent())
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .addAction(new Notification.Action.Builder(null, "停止并退出服务", stop).build())
                .build();
    }

    private void updateNotification(String message) {
        main.post(() -> {
            if (!destroyed && !message.equals(previousMessage)
                    && (Build.VERSION.SDK_INT < 33 || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED)) {
                previousMessage = message;
                getSystemService(NotificationManager.class).notify(NOTIFICATION_ID, notification(message));
            }
        });
    }

    private void refreshStatus() {
        if (destroyed) return;
        try {
            JSONObject status = new JSONObject(RuntimeHost.module().callAttr("status_json").toString());
            boolean active = status.optBoolean("running");
            synchronized (this) {
                if (destroyed) return;
                if (active && (!wakeLock.isHeld() || android.os.SystemClock.elapsedRealtime() - lastWakeRenewal > 300_000)) {
                    wakeLock.acquire(600_000);
                    lastWakeRenewal = android.os.SystemClock.elapsedRealtime();
                } else if (!active && wakeLock.isHeld()) {
                    wakeLock.release();
                }
            }
            updateNotification(status.optBoolean("waiting") ? "等待北京时间定时启动 · 请保留此通知" : active ? "正在查询并预约座位 · 请保留此通知" : "本地面板运行中 · 点此打开");
            JSONObject result = status.optJSONObject("last_result");
            if (result != null && "reserved".equals(result.optString("status"))) {
                String identity = result.toString();
                if (!identity.equals(previousSuccess)) {
                    previousSuccess = identity;
                    Notification resultNotification = builder(RESULTS).setSmallIcon(R.drawable.ic_notification)
                            .setContentTitle("座位预约成功")
                            .setContentText("打开应用查看座位和使用时段")
                            .setContentIntent(openIntent()).setAutoCancel(true).build();
                    main.post(() -> {
                        if (!destroyed && (Build.VERSION.SDK_INT < 33
                                || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED)) {
                            getSystemService(NotificationManager.class).notify(2, resultNotification);
                        }
                    });
                }
            }
        } catch (Exception ignored) {
            // Do not send Python exceptions or reservation responses to Logcat.
        }
    }

    @Override public IBinder onBind(Intent intent) { return binder; }

    private void shutdown() {
        if (destroyed) return;
        destroyed = true;
        url = null;
        monitor.shutdownNow();
        synchronized (this) {
            if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        }
        RuntimeHost.LIFECYCLE.execute(() -> {
            try { RuntimeHost.stop(); } catch (Exception ignored) { }
        });
        stopForeground(STOP_FOREGROUND_REMOVE);
    }

    @Override public void onDestroy() {
        shutdown();
        super.onDestroy();
    }
}
