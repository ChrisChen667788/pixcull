  window.PixCullWebRTC = (function() {
    const RELAY_POST = "/sync/webrtc/relay";
    const RELAY_INBOX = "/api/v1/sync/webrtc/inbox";
    const ICE_SERVERS = [{ urls: "stun:stun.l.google.com:19302" }];
    const OPEN_TIMEOUT_MS = 5000;
    const INBOX_POLL_MS = 500;

    function _supported() {
      return typeof RTCPeerConnection === "function";
    }

    async function _post(body) {
      try {
        const r = await fetch(RELAY_POST, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify(body),
        });
        return r.ok ? await r.json() : null;
      } catch (e) { return null; }
    }

    async function _pollInbox(peerId, sinceMs) {
      const url = `${RELAY_INBOX}?peer=${encodeURIComponent(peerId)}` +
                  `&since=${sinceMs|0}`;
      try {
        const r = await fetch(url, { headers: { "Accept": "application/json" }});
        if (!r.ok) return [];
        const d = await r.json();
        return (d && d.messages) || [];
      } catch (e) { return []; }
    }

    // Connect from `selfId` to `targetId`.  Resolves with an open
    // RTCDataChannel or null on timeout / unsupported.
    async function connect(selfId, targetId) {
      if (!_supported() || !selfId || !targetId) return null;
      const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
      const dc = pc.createDataChannel("pixcull-sync");
      let lastSince = 0;
      let polling = true;

      pc.onicecandidate = ev => {
        if (ev.candidate) {
          _post({
            kind: "candidate", from: selfId, to: targetId,
            payload: ev.candidate.toJSON(),
          });
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      _post({
        kind: "offer", from: selfId, to: targetId,
        payload: { sdp: offer.sdp, type: offer.type },
      });

      const open = new Promise(resolve => {
        let resolved = false;
        const settle = v => { if (!resolved) { resolved = true; resolve(v); } };
        dc.onopen = () => settle(dc);
        setTimeout(() => settle(null), OPEN_TIMEOUT_MS);

        (async () => {
          while (polling && !resolved) {
            const msgs = await _pollInbox(selfId, lastSince);
            for (const m of msgs) {
              lastSince = Math.max(lastSince, m.ts_ms|0);
              if (m.kind === "answer" && m.from === targetId
                  && !pc.remoteDescription) {
                try { await pc.setRemoteDescription(m.payload); }
                catch (e) { settle(null); return; }
              } else if (m.kind === "candidate" && m.from === targetId) {
                try { await pc.addIceCandidate(m.payload); }
                catch (e) { /* candidate gathering ongoing — ignore */ }
              } else if (m.kind === "bye" && m.from === targetId) {
                settle(null); return;
              }
            }
            await new Promise(r => setTimeout(r, INBOX_POLL_MS));
          }
        })();
      });
      const ch = await open;
      polling = false;
      if (ch === null) { try { pc.close(); } catch(e){} }
      return ch;
    }

    return { connect, supported: _supported };
  })();
