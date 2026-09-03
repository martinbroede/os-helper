/**
 * <event-editor> — a self-contained Web Component for editing and pushing a
 * raw JSON event to the OpenSearch helper backend.
 *
 * Attributes:
 *   endpoint  URL the event is POSTed to. Default: "/api/events".
 *   index     Initial value for the target-index input field. The user can
 *             edit it; the value at push time is appended as ?index=.
 *   placeholder  Placeholder text for the editor textarea.
 *
 * Events (bubble + composed, so they cross the shadow boundary):
 *   event-pushed   detail: { response }  — dispatched on a successful push.
 *   event-error    detail: { message }   — dispatched on any failure.
 *
 * The component has no external dependencies, uses shadow DOM for style
 * encapsulation, and supports any number of instances on a single page.
 */
class EventEditor extends HTMLElement {
  static get observedAttributes() {
    return ["endpoint", "index", "placeholder"];
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._onPush = this._onPush.bind(this);
    // If value/indexValue were assigned before this element was upgraded
    // (e.g. the host script ran before event-editor.js loaded), those
    // assignments sit as own properties that shadow the accessors below.
    // Re-route them through the setters so state restore/capture works.
    this._upgradeProperty("value");
    this._upgradeProperty("indexValue");
  }

  _upgradeProperty(prop) {
    if (Object.prototype.hasOwnProperty.call(this, prop)) {
      const v = this[prop];
      delete this[prop];
      this[prop] = v;
    }
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    // Re-render only if already rendered (attributes may change post-connect).
    if (this.shadowRoot.childElementCount > 0) {
      const doc = this._textarea ? this._textarea.value : "";
      const idx = this._indexInput ? this._indexInput.value : "";
      this._render();
      if (this._textarea) this._textarea.value = doc;
      if (this._indexInput && idx) this._indexInput.value = idx;
    }
  }

  get endpoint() {
    return this.getAttribute("endpoint") || "/api/events";
  }

  get index() {
    return this.getAttribute("index") || "";
  }

  get placeholder() {
    return (
      this.getAttribute("placeholder") ||
      '{\n  "message": "hello world",\n  "level": "info"\n}'
    );
  }

  /**
   * Live JSON content of the editor textarea. Readable/writable at any time —
   * before the element is rendered, the assignment is buffered and applied on
   * the next render. Lets a host page snapshot and restore editor state.
   */
  get value() {
    return this._textarea ? this._textarea.value : this._pendingValue || "";
  }

  set value(v) {
    this._pendingValue = v == null ? "" : String(v);
    if (this._textarea) this._textarea.value = this._pendingValue;
  }

  /** Live value of the target-index input (as opposed to the seed attribute). */
  get indexValue() {
    return this._indexInput ? this._indexInput.value : this._pendingIndex || "";
  }

  set indexValue(v) {
    this._pendingIndex = v == null ? "" : String(v);
    if (this._indexInput) this._indexInput.value = this._pendingIndex;
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
          --ee-accent: #0b5fff;
          --ee-border: #d0d7de;
          --ee-radius: 8px;
          color: #1f2328;
          box-sizing: border-box;
        }
        :host([hidden]) { display: none; }
        * { box-sizing: border-box; }
        .card {
          border: 1px solid var(--ee-border);
          border-radius: var(--ee-radius);
          padding: 16px;
          background: #fff;
        }
        .heading {
          margin: 0 0 12px;
          font-size: 1rem;
          font-weight: 600;
        }
        .field {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 10px;
        }
        .field label {
          font-size: 0.8rem;
          font-weight: 600;
          color: #57606a;
          white-space: nowrap;
        }
        input.index {
          flex: 1;
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          font-size: 0.875rem;
          padding: 8px 10px;
          border: 1px solid var(--ee-border);
          border-radius: var(--ee-radius);
          outline: none;
        }
        input.index:focus { border-color: var(--ee-accent); }
        textarea {
          width: 100%;
          min-height: 160px;
          resize: vertical;
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          font-size: 0.875rem;
          line-height: 1.5;
          padding: 10px 12px;
          border: 1px solid var(--ee-border);
          border-radius: var(--ee-radius);
          outline: none;
          tab-size: 2;
        }
        textarea:focus { border-color: var(--ee-accent); }
        .toolbar {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-top: 12px;
        }
        button {
          font: inherit;
          font-weight: 600;
          color: #fff;
          background: var(--ee-accent);
          border: none;
          border-radius: var(--ee-radius);
          padding: 8px 18px;
          cursor: pointer;
        }
        button:hover:not(:disabled) { filter: brightness(0.95); }
        button:disabled { opacity: 0.6; cursor: default; }
        .format {
          color: var(--ee-accent);
          background: transparent;
          border: 1px solid var(--ee-border);
        }
        .count {
          margin-left: auto;
          font-size: 0.8rem;
          font-weight: 600;
          color: #57606a;
          background: #eaeef2;
          border-radius: 999px;
          padding: 4px 10px;
          min-width: 1.5rem;
          text-align: center;
        }
        .status {
          margin-top: 12px;
          padding: 10px 12px;
          border-radius: var(--ee-radius);
          font-size: 0.875rem;
          display: none;
          white-space: pre-wrap;
          word-break: break-word;
        }
        .status.show { display: block; }
        .status.success { background: #e6f4ea; color: #14632b; }
        .status.error { background: #fce8e6; color: #a50e0e; }
      </style>
      <div class="card">
        <div class="field">
          <label for="index-input">Index</label>
          <input id="index-input" class="index" part="index" type="text"
            spellcheck="false" placeholder="events"
            value="${this._escape(this.index)}" />
        </div>
        <textarea part="input" spellcheck="false" placeholder="${this._escape(
          this.placeholder
        )}"></textarea>
        <div class="toolbar">
          <button type="button" part="button" class="push">Push</button>
          <button type="button" class="format">Format</button>
          <span class="count" part="count" title="Pushes this session">0</span>
        </div>
        <div class="status" role="status" aria-live="polite"></div>
      </div>
    `;

    this._textarea = this.shadowRoot.querySelector("textarea");
    this._indexInput = this.shadowRoot.querySelector("input.index");
    this._pushBtn = this.shadowRoot.querySelector(".push");
    this._formatBtn = this.shadowRoot.querySelector(".format");
    this._count = this.shadowRoot.querySelector(".count");
    this._status = this.shadowRoot.querySelector(".status");

    // Re-apply any values buffered before this (re-)render so live state and
    // pre-connect assignments survive attribute-driven re-renders.
    if (this._pendingValue != null) this._textarea.value = this._pendingValue;
    if (this._pendingIndex != null) this._indexInput.value = this._pendingIndex;
    // Session-only push counter — deliberately never persisted, so it resets
    // on reload. Re-applied here so an attribute-driven re-render keeps it.
    if (this._pushCount == null) this._pushCount = 0;
    this._count.textContent = String(this._pushCount);

    this._pushBtn.addEventListener("click", this._onPush);
    this._formatBtn.addEventListener("click", () => this._format());
  }

  _escape(text) {
    return String(text).replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }

  _showStatus(message, kind) {
    this._status.textContent = message;
    this._status.className = `status show ${kind}`;
  }

  _format() {
    const raw = this._textarea.value.trim();
    if (!raw) return;
    try {
      this._textarea.value = JSON.stringify(JSON.parse(raw), null, 2);
      this._status.className = "status";
    } catch (err) {
      this._showStatus(`Invalid JSON: ${err.message}`, "error");
    }
  }

  async _onPush() {
    // Count every press of the Push button for this session (in-memory only).
    this._pushCount = (this._pushCount || 0) + 1;
    this._count.textContent = String(this._pushCount);

    const raw = this._textarea.value.trim();
    if (!raw) {
      this._fail("Please enter a JSON event before pushing.");
      return;
    }

    // Validate client-side so obvious mistakes never reach the network.
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (err) {
      this._fail(`Invalid JSON: ${err.message}`);
      return;
    }
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      this._fail("Event must be a JSON object.");
      return;
    }

    const index = this._indexInput.value.trim();
    if (!index) {
      this._fail("Please enter a target index.");
      return;
    }

    let url = this.endpoint;
    url += `${url.includes("?") ? "&" : "?"}index=${encodeURIComponent(index)}`;

    this._pushBtn.disabled = true;
    this._pushBtn.textContent = "Pushing…";
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsed),
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        this._fail(data.message || `Request failed (HTTP ${res.status}).`);
        return;
      }

      this._showStatus(
        `Pushed to "${data.index}" (id: ${data.id}, ${data.result}).`,
        "success"
      );
      this.dispatchEvent(
        new CustomEvent("event-pushed", {
          detail: { response: data },
          bubbles: true,
          composed: true,
        })
      );
    } catch (err) {
      this._fail(`Network error: ${err.message}`);
    } finally {
      this._pushBtn.disabled = false;
      this._pushBtn.textContent = "Push";
    }
  }

  _fail(message) {
    this._showStatus(message, "error");
    this.dispatchEvent(
      new CustomEvent("event-error", {
        detail: { message },
        bubbles: true,
        composed: true,
      })
    );
  }
}

customElements.define("event-editor", EventEditor);
