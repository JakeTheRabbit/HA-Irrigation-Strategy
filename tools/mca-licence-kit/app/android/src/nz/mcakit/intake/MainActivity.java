package nz.mcakit.intake;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognizerIntent;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.Iterator;

/**
 * Hosts the intake questionnaire (assets/web/index.html) in a WebView and gives it
 * voice input, camera, photo picking, GPS and email sending through the "Android" bridge.
 * All interview data stays on the phone until the user sends the email.
 */
public class MainActivity extends Activity {

    private static final int REQ_SPEECH = 11;
    private static final int REQ_PICK = 12;
    private static final int REQ_CAMERA = 13;
    private static final int REQ_LOC_PERM = 14;

    private WebView web;
    private final Handler ui = new Handler(Looper.getMainLooper());

    // State of the pending activity request (one at a time).
    private String pendingQid;
    private String pendingInterview;
    private String pendingCameraName;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        web = new WebView(this);
        setContentView(web);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(false);
        s.setDatabaseEnabled(true);
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                if (url.startsWith("file:///android_asset/")) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                } catch (Exception ignored) { }
                return true;
            }
        });
        web.addJavascriptInterface(new Bridge(), "Android");
        if (savedInstanceState != null) {
            pendingQid = savedInstanceState.getString("qid");
            pendingInterview = savedInstanceState.getString("iid");
            pendingCameraName = savedInstanceState.getString("cam");
        }
        web.loadUrl("file:///android_asset/web/index.html");
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        out.putString("qid", pendingQid);
        out.putString("iid", pendingInterview);
        out.putString("cam", pendingCameraName);
    }

    @Override
    public void onBackPressed() {
        web.evaluateJavascript("window.onBack && window.onBack()", new android.webkit.ValueCallback<String>() {
            @Override
            public void onReceiveValue(String handled) {
                if (!"true".equals(handled)) MainActivity.super.onBackPressed();
            }
        });
    }

    // ---------------------------------------------------------------- helpers

    private void js(final String code) {
        ui.post(new Runnable() {
            @Override
            public void run() { web.evaluateJavascript(code, null); }
        });
    }

    private static String q(String s) {
        return JSONObject.quote(s == null ? "" : s);
    }

    /** Only letters, digits, dot, dash and underscore: no path traversal from the page. */
    static String safe(String s) {
        if (s == null) return "x";
        String r = s.replaceAll("[^A-Za-z0-9._-]", "_");
        if (r.isEmpty() || r.startsWith(".")) r = "x" + r;
        return r.length() > 80 ? r.substring(0, 80) : r;
    }

    private File interviewDir(String iid) {
        File d = new File(new File(getFilesDir(), FileShareProvider.ROOT), safe(iid));
        d.mkdirs();
        return d;
    }

    private Uri uriFor(String iid, String name) {
        return Uri.parse("content://" + FileShareProvider.AUTHORITY + "/" + safe(iid) + "/" + safe(name));
    }

    private void copy(Uri src, File dst) throws Exception {
        InputStream in = getContentResolver().openInputStream(src);
        OutputStream out = new FileOutputStream(dst);
        try {
            byte[] b = new byte[65536];
            int n;
            while ((n = in.read(b)) > 0) out.write(b, 0, n);
        } finally {
            in.close();
            out.close();
        }
    }

    private String nextName(String iid, String qid, String ext) {
        File d = interviewDir(iid);
        int i = 1;
        String n;
        do {
            n = safe(qid) + "_" + (i < 10 ? "0" : "") + i + "." + ext;
            i++;
        } while (new File(d, n).exists());
        return n;
    }

    // ---------------------------------------------------------------- bridge

    private class Bridge {

        @JavascriptInterface
        public void speak(final String qid, final String prompt) {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    pendingQid = qid;
                    Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
                    i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
                    i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-NZ");
                    i.putExtra(RecognizerIntent.EXTRA_PROMPT, prompt);
                    i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
                    try {
                        startActivityForResult(i, REQ_SPEECH);
                    } catch (ActivityNotFoundException e) {
                        js("window.onSpeech(" + q(qid) + ",'',"
                                + q("No voice service. Install the Google app, or use the keyboard microphone.") + ")");
                    }
                }
            });
        }

        @JavascriptInterface
        public void pickPhotos(final String iid, final String qid) {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    pendingQid = qid;
                    pendingInterview = iid;
                    Intent i = new Intent(Intent.ACTION_GET_CONTENT);
                    i.setType("image/*");
                    i.addCategory(Intent.CATEGORY_OPENABLE);
                    i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                    try {
                        startActivityForResult(Intent.createChooser(i, "Add photos"), REQ_PICK);
                    } catch (ActivityNotFoundException e) {
                        js("window.onPhotos(" + q(qid) + ",'[]'," + q("No photo app found.") + ")");
                    }
                }
            });
        }

        @JavascriptInterface
        public void takePhoto(final String iid, final String qid) {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    pendingQid = qid;
                    pendingInterview = iid;
                    pendingCameraName = nextName(iid, qid, "jpg");
                    Intent i = new Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE);
                    Uri out = uriFor(iid, pendingCameraName);
                    i.putExtra(android.provider.MediaStore.EXTRA_OUTPUT, out);
                    i.setClipData(ClipData.newRawUri("photo", out));
                    i.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    try {
                        startActivityForResult(i, REQ_CAMERA);
                    } catch (ActivityNotFoundException e) {
                        js("window.onPhotos(" + q(qid) + ",'[]'," + q("No camera app found.") + ")");
                    }
                }
            });
        }

        @JavascriptInterface
        public void removeFile(String iid, String name) {
            new File(interviewDir(iid), safe(name)).delete();
        }

        @JavascriptInterface
        public void deleteInterview(String iid) {
            File d = interviewDir(iid);
            File[] fs = d.listFiles();
            if (fs != null) for (File f : fs) f.delete();
            d.delete();
        }

        @JavascriptInterface
        public void gps(final String qid) {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    pendingQid = qid;
                    if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
                        requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION,
                                Manifest.permission.ACCESS_COARSE_LOCATION}, REQ_LOC_PERM);
                    } else {
                        locate(qid);
                    }
                }
            });
        }

        @JavascriptInterface
        public void send(final String to, final String subject, final String body, final String json,
                         final String imagesJson, final String photosJson, final String iid) {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    try {
                        File d = interviewDir(iid);
                        ArrayList<Uri> uris = new ArrayList<Uri>();

                        FileOutputStream fo = new FileOutputStream(new File(d, "intake.json"));
                        fo.write(json.getBytes("UTF-8"));
                        fo.close();
                        uris.add(uriFor(iid, "intake.json"));

                        JSONObject imgs = new JSONObject(imagesJson);
                        Iterator<String> keys = imgs.keys();
                        while (keys.hasNext()) {
                            String name = safe(keys.next());
                            String dataUrl = imgs.getString(name);
                            int comma = dataUrl.indexOf(',');
                            byte[] png = Base64.decode(dataUrl.substring(comma + 1), Base64.DEFAULT);
                            FileOutputStream po = new FileOutputStream(new File(d, name));
                            po.write(png);
                            po.close();
                            uris.add(uriFor(iid, name));
                        }

                        JSONArray ph = new JSONArray(photosJson);
                        for (int k = 0; k < ph.length(); k++) {
                            String name = safe(ph.getString(k));
                            if (new File(d, name).exists()) uris.add(uriFor(iid, name));
                        }

                        Intent i = new Intent(Intent.ACTION_SEND_MULTIPLE);
                        i.setType("application/octet-stream");
                        if (to != null && to.trim().length() > 0) {
                            i.putExtra(Intent.EXTRA_EMAIL, to.trim().split("\\s*[,;]\\s*"));
                        }
                        i.putExtra(Intent.EXTRA_SUBJECT, subject);
                        i.putExtra(Intent.EXTRA_TEXT, body);
                        i.putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris);
                        ClipData clip = ClipData.newRawUri("intake", uris.get(0));
                        for (int k = 1; k < uris.size(); k++) clip.addItem(new ClipData.Item(uris.get(k)));
                        i.setClipData(clip);
                        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                        startActivity(Intent.createChooser(i, "Send intake by email"));
                    } catch (Exception e) {
                        js("window.onSendError(" + q("Could not prepare the email: " + e.getMessage()) + ")");
                    }
                }
            });
        }
    }

    // ---------------------------------------------------------------- results

    private void locate(final String qid) {
        final LocationManager lm = (LocationManager) getSystemService(LOCATION_SERVICE);
        try {
            Location best = null;
            for (String p : lm.getProviders(true)) {
                Location l = lm.getLastKnownLocation(p);
                if (l != null && (best == null || l.getAccuracy() < best.getAccuracy())) best = l;
            }
            final boolean[] done = {false};
            final LocationListener listener = new LocationListener() {
                @Override public void onLocationChanged(Location l) {
                    if (done[0]) return;
                    done[0] = true;
                    lm.removeUpdates(this);
                    js("window.onGps(" + q(qid) + "," + l.getLatitude() + "," + l.getLongitude() + "," + l.getAccuracy() + ")");
                }
                @Override public void onStatusChanged(String p, int s, Bundle b) { }
                @Override public void onProviderEnabled(String p) { }
                @Override public void onProviderDisabled(String p) { }
            };
            String provider = lm.isProviderEnabled(LocationManager.GPS_PROVIDER) ? LocationManager.GPS_PROVIDER
                    : LocationManager.NETWORK_PROVIDER;
            lm.requestLocationUpdates(provider, 0, 0, listener, Looper.getMainLooper());
            final Location fallback = best;
            ui.postDelayed(new Runnable() {
                @Override public void run() {
                    if (done[0]) return;
                    done[0] = true;
                    lm.removeUpdates(listener);
                    if (fallback != null) {
                        js("window.onGps(" + q(qid) + "," + fallback.getLatitude() + "," + fallback.getLongitude() + ","
                                + fallback.getAccuracy() + ")");
                    } else {
                        js("window.onGps(" + q(qid) + ",0,0,0," + q("No GPS fix. Go outside and try again.") + ")");
                    }
                }
            }, 25000);
        } catch (SecurityException e) {
            js("window.onGps(" + q(qid) + ",0,0,0," + q("Location permission is off.") + ")");
        } catch (Exception e) {
            js("window.onGps(" + q(qid) + ",0,0,0," + q("Location is off. Turn it on in Settings.") + ")");
        }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        if (code == REQ_LOC_PERM) {
            if (res.length > 0 && res[0] == PackageManager.PERMISSION_GRANTED) locate(pendingQid);
            else js("window.onGps(" + q(pendingQid) + ",0,0,0," + q("Location permission is off.") + ")");
        }
    }

    @Override
    protected void onActivityResult(int code, int result, Intent data) {
        super.onActivityResult(code, result, data);
        if (code == REQ_SPEECH) {
            if (result == RESULT_OK && data != null) {
                ArrayList<String> r = data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS);
                String text = (r != null && !r.isEmpty()) ? r.get(0) : "";
                js("window.onSpeech(" + q(pendingQid) + "," + q(text) + ")");
            } else {
                js("window.onSpeech(" + q(pendingQid) + ",''," + q("Nothing heard") + ")");
            }
        } else if (code == REQ_PICK) {
            JSONArray names = new JSONArray();
            if (result == RESULT_OK && data != null) {
                ArrayList<Uri> picked = new ArrayList<Uri>();
                if (data.getClipData() != null) {
                    for (int i = 0; i < data.getClipData().getItemCount(); i++) picked.add(data.getClipData().getItemAt(i).getUri());
                } else if (data.getData() != null) {
                    picked.add(data.getData());
                }
                for (Uri u : picked) {
                    try {
                        String type = getContentResolver().getType(u);
                        String ext = type != null && type.contains("png") ? "png" : "jpg";
                        String n = nextName(pendingInterview, pendingQid, ext);
                        copy(u, new File(interviewDir(pendingInterview), n));
                        names.put(n);
                    } catch (Exception ignored) { }
                }
            }
            js("window.onPhotos(" + q(pendingQid) + "," + q(names.toString()) + ")");
        } else if (code == REQ_CAMERA) {
            JSONArray names = new JSONArray();
            File f = new File(interviewDir(pendingInterview), safe(pendingCameraName));
            if (result == RESULT_OK && f.exists() && f.length() > 0) names.put(pendingCameraName);
            else f.delete();
            js("window.onPhotos(" + q(pendingQid) + "," + q(names.toString()) + ")");
        }
    }
}
