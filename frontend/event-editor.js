/**
 * <event-editor> — a self-contained Web Component for editing and pushing a
 * raw JSON event to the OpenSearch helper backend.
 *
 * Attributes:
 *   endpoint  URL the event is POSTed to. Default: "/api/events".
 *   index     Optional target index; appended as a ?index= query parameter.
 *   placeholder  Placeholder text for the editor textarea.
 *
 * Events (bubble + composed, so they cross the shadow boundary):
 *   event-pushed   detail: { response }  — dispatched on a successful push.
 *   event-error    detail: { message }   — dispatched on any failure.
 *
 * Slots:
 *   heading   Optional custom heading content above the editor.
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
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    // Re-render only if already rendered (attributes may change post-connect).
    if (this.shadowRoot.childElementCount > 0) {
      const value = this._textarea ? this._textarea.value : "";
      this._render();
      if (this._textarea) this._textarea.value = value;
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
        <slot name="heading"><h3 class="heading">Event Editor</h3></slot>
        <textarea part="input" spellcheck="false" placeholder="${this._escape(
          this.placeholder
        )}"></textarea>
        <div class="toolbar">
          <button type="button" part="button" class="push">Push</button>
          <button type="button" class="format">Format</button>
        </div>
        <div class="status" role="status" aria-live="polite"></div>
      </div>
    `;

    this._textarea = this.shadowRoot.querySelector("textarea");
    this._pushBtn = this.shadowRoot.querySelector(".push");
    this._formatBtn = this.shadowRoot.querySelector(".format");
    this._status = this.shadowRoot.querySelector(".status");

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

    let url = this.endpoint;
    if (this.index) {
      url += `${url.includes("?") ? "&" : "?"}index=${encodeURIComponent(
        this.index
      )}`;
    }

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
