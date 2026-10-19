# -*- coding: utf-8 -*-
"""피식니혼고 인스타 클라우드 발행 (2026-10-13) — GitHub Actions 에서 돈다. 찬작 cloud_publish.py 를 줄인 것.

큐 = 이 저장소의 초안(draft) 릴리스. 초안은 저장소 권한자만 보인다 — 발행 전 영상·캡션이 새지 않는다.
  태그 q-<순서>-<발음>, 본문 JSON {name, style, due, caption, done}, 첨부 video.mp4.  노트북 발행.py --stage 가 만든다.
실행: 발행 시각(due)이 지났고 3시간 안이면 올린다(12:30 편이 21:00 편과 붙어 나가지 않게). 넘었으면 missed 로 남긴다.
한 번 실행에 1편만. 영상 공개 URL = media/ 에 잠깐 올려 Pages 로 열고, 게시 후 지운다.
결과 = log.json (노트북 발행.py --pull 이 읽는다). 비밀값 IG_TOKEN = 인스타 장기 토큰 문자열.
"""
import datetime as dt, json, os, subprocess, sys, time, urllib.parse, urllib.request, urllib.error

REPO = os.environ.get("GITHUB_REPOSITORY", "kuo97/pisik-nihongo-media")
GH = os.environ.get("GITHUB_TOKEN", "")
IG = (os.environ.get("IG_TOKEN") or "").replace("﻿", "").strip()   # 윈도우 PowerShell 로 등록하면 BOM 이 붙는다
TH = (os.environ.get("THREADS_TOKEN") or "").replace("﻿", "").strip()   # 10-20 쓰레드 연결 — 없으면 쓰레드는 건너뜀
TH_API = "https://graph.threads.net/v1.0/"
PAGES = "https://kuo97.github.io/pisik-nihongo-media/"
API = "https://graph.instagram.com/v21.0/"
KST = dt.timezone(dt.timedelta(hours=9))
LOG = "log.json"
LATE = dt.timedelta(hours=3)


def now():
    return dt.datetime.now(KST)


def gh(method, path, body=None):
    url = "https://api.github.com/repos/%s/%s" % (REPO, path)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + GH, "Accept": "application/vnd.github+json",
        "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        t = r.read().decode()
        return json.loads(t) if t else {}


def ig(path, data=None):
    """토큰은 본문·주소로만 보내고, 오류에는 응답 본문만 남긴다."""
    if data is None:
        url = API + path + ("&" if "?" in path else "?") + "access_token=" + IG
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(API + path, data=urllib.parse.urlencode(dict(data, access_token=IG)).encode())
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError("API %s: %s" % (e.code, e.read().decode()[:400]))


def git(*a):
    return subprocess.run(["git"] + list(a), capture_output=True, text=True)


def commit_push(paths, msg):
    git("add", "-A", *paths)
    if not git("status", "--porcelain", *paths).stdout.strip():
        return
    git("commit", "-q", "-m", msg)
    for _ in range(4):
        if git("push", "-q").returncode == 0:
            return
        git("pull", "-q", "--rebase")
    raise RuntimeError("git push 실패: " + msg)


def pages_build():
    try:
        gh("POST", "pages/builds")          # GITHUB_TOKEN push 는 Pages 빌드를 안 걸 수 있다
    except Exception as e:
        print("  pages 빌드 요청 실패(무시):", e)


def host(local, name):
    os.makedirs("media", exist_ok=True)
    os.replace(local, "media/" + name)
    commit_push(["media"], "media: " + name)
    pages_build()
    url = PAGES + "media/" + name
    for i in range(48):
        try:
            if urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=15).status == 200:
                print("  공개 확인 %d초" % ((i + 1) * 15))
                return url
        except Exception:
            pass
        time.sleep(15)
    raise RuntimeError("Pages 에 영상이 12분 안에 안 열렸다")


def unhost(name):
    p = "media/" + name
    if os.path.exists(p):
        os.remove(p)
        commit_push(["media"], "media: remove " + name)
        pages_build()


def publish(url, caption):
    c = ig("me/media", {"media_type": "REELS", "video_url": url, "caption": caption, "share_to_feed": "true"})
    for _ in range(60):
        time.sleep(10)
        st = ig(c["id"] + "?fields=status_code,status")
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError("인스타 처리 실패: %s" % st.get("status"))
    else:
        raise RuntimeError("인스타 처리 10분 초과")
    return ig("me/media_publish", {"creation_id": c["id"]})["id"]


def th(path, data=None):
    if data is None:
        req = urllib.request.Request(TH_API + path + ("&" if "?" in path else "?") + "access_token=" + TH)
    else:
        req = urllib.request.Request(TH_API + path, data=urllib.parse.urlencode(dict(data, access_token=TH)).encode())
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError("Threads %s: %s" % (e.code, e.read().decode()[:400]))


def threads_post(rel, m):
    """인스타가 올라간 뒤 쓰레드에 글 + 정답 카드 이미지. 실패해도 인스타 발행에는 영향 없다."""
    if not TH or not m.get("threads"):
        return None
    name = "%d_%s.jpg" % (int(time.time()), rel["tag_name"])
    try:
        url = host(download(rel, "card.jpg", "_card.jpg"), name)
        c = th("me/threads", {"media_type": "IMAGE", "image_url": url, "text": m["threads"]})
        for _ in range(18):
            time.sleep(10)
            st = th(c["id"] + "?fields=status,error_message")
            if st.get("status") == "FINISHED":
                break
            if st.get("status") in ("ERROR", "EXPIRED"):
                raise RuntimeError("쓰레드 처리 실패: %s" % st.get("error_message"))
        tid = th("me/threads_publish", {"creation_id": c["id"]})["id"]
        print("  [쓰레드 OK] %s" % tid)
        return tid
    except Exception as e:
        print("  [쓰레드 실패] %s" % e)
        return "실패: " + str(e)[:200]
    finally:
        unhost(name)


def record(m, status, **kw):
    try:
        L = json.load(open(LOG, encoding="utf-8"))
    except Exception:
        L = {"entries": []}
    e = {"name": m["name"], "style": m["style"], "due": m["due"], "status": status,
         "at": now().strftime("%Y-%m-%dT%H:%M:%S+09:00")}
    e.update({k: v for k, v in kw.items() if v})
    L["entries"] = (L["entries"] + [e])[-500:]
    json.dump(L, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    commit_push([LOG], "log: %s %s" % (m["name"], status))


def patch_body(rel, m):
    gh("PATCH", "releases/%d" % rel["id"], {"body": json.dumps(m, ensure_ascii=False), "tag_name": rel["tag_name"]})


def download(rel, asset="video.mp4", out="_dl.mp4"):
    a = [x for x in rel.get("assets", []) if x["name"] == asset]
    if not a:
        raise RuntimeError(asset + " 첨부 없음")
    r = subprocess.run(["curl", "-sSL", "--fail", "-o", out, "-H", "Authorization: Bearer " + GH,
                        "-H", "Accept: application/octet-stream", a[0]["url"]], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(asset + " 내려받기 실패: " + r.stderr[-200:])
    return out


def run(force=None):
    if not IG:
        sys.exit("비밀값 IG_TOKEN 이 없다")
    rels = gh("GET", "releases?per_page=100")
    q = sorted([r for r in rels if r.get("draft") and (r.get("tag_name") or "").startswith("q-")],
               key=lambda r: json.loads(r["body"])["due"])
    t = now()
    print("큐 %d건 · 지금 %s KST" % (len(q), t.strftime("%m-%d %H:%M")))
    for rel in q:
        m = json.loads(rel["body"])
        if m.get("done"):
            gh("DELETE", "releases/%d" % rel["id"])
            continue
        due = dt.datetime.fromisoformat(m["due"])
        if force and m["name"] != force:
            continue
        if not force:
            if t < due:
                wait = (due - t).total_seconds()
                if wait > 600:
                    continue                          # 아직 멀었다 — 다음 실행에서
                print("  %s 발행 시각까지 %d초 대기" % (m["name"], wait))
                time.sleep(wait)
            elif t - due > LATE:
                if not m.get("missed"):
                    print("  %s 3시간 넘게 지났다(%s) — 올리지 않음" % (m["name"], m["due"]))
                    record(m, "missed", error="발행 시각에서 3시간 넘게 지나 자동 발행 안 함")
                    m["missed"] = True
                    patch_body(rel, m)
                continue
        print("▶ %s (%s) %s" % (m["name"], m["style"], m["due"]))
        name = "%d_%s.mp4" % (int(time.time()), rel["tag_name"])
        try:
            mid = publish(host(download(rel), name), m["caption"])
            m["done"] = mid
            patch_body(rel, m)                        # 먼저 적는다 — 중간에 죽어도 두 번 올리지 않게
            unhost(name)
            tid = threads_post(rel, m)
            record(m, "published", media_id=mid, threads=tid)
            print("  [OK] %s" % mid)
            gh("DELETE", "releases/%d" % rel["id"])
        except Exception as e:
            print("  [실패] %s" % e)
            record(m, "failed", error=str(e)[:300])
        finally:
            unhost(name)
        return                                        # 한 번에 1편만


def test_hosting():
    """게시 없이 Pages 호스팅·토큰만 시험한다 (mode=test)."""
    me = ig("me?fields=username")
    print("[OK] 토큰 계정:", me.get("username"))
    if TH:
        print("[OK] 쓰레드 계정:", th("me?fields=username").get("username"))
    open("_t.txt", "w").write("ok")
    name = "%d_hosting-test.txt" % int(time.time())
    try:
        host("_t.txt", name)
        print("[OK] 호스팅 시험 통과")
    finally:
        unhost(name)


if __name__ == "__main__":
    git("config", "user.name", "pisik-cloud")
    git("config", "user.email", "actions@users.noreply.github.com")
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    if mode == "test":
        test_hosting()
    else:
        run(force=sys.argv[2] if len(sys.argv) > 2 else None)
