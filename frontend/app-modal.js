/**
 * <app-modal> — a self-contained Web Component for a dialog overlay with a
 * header (custom text) and a close button. Body content is projected via the
 * default slot, so the host page owns whatever goes inside.
 *
 * Attributes:
 *   heading  Text shown in the modal header. May also be provided via the
 *            `heading` slot for rich markup; the slot wins when both are set.
 *   open     Presence reflects visibility. Add it (or call show()) to open,
 *            remove it (or call hide()) to close.
 *   no-backdrop-close  If present, clicking the backdrop does NOT close the
 *            modal (Escape and the close button still do).
 *
 * Properties / methods:
 *   open       Boolean mirror of the attribute.
 *   show()     Opens the modal.
 *   hide()     Closes the modal.
 *   toggle()   Flips open state.
 *
 * Events (bubble + composed, so they cross the shadow boundary):
 *   modal-open    — dispatched when the modal becomes visible.
 *   modal-close   detail: { reason }  — dispatched when it closes. `reason` is
 *                 "close-button", "backdrop", "escape", or "api".
 *
 * CSS parts: `backdrop`, `dialog`, `header`, `title`, `close`, `body`.
 * Slots: default (body content), `heading` (header content).
 *
 * The component has no external dependencies, uses shadow DOM for style
 * encapsulation, and supports any number of instances on a single page.
 */
class AppModal extends HTMLElement {
  static get observedAttributes() {
    return ["heading", "open"];
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._onKeydown = this._onKeydown.bind(this);
    this._onBackdrop = this._onBackdrop.bind(this);
  }

  connectedCallback() {
    this._render();
    // Listen at the document level so Escape works regardless of focus.
    document.addEventListener("keydown", this._onKeydown);
  }

  disconnectedCallback() {
    document.removeEventListener("keydown", this._onKeydown);
  }

  attributeChangedCallback(name, oldValue, newValue) {
    // Re-render heading text in place; toggle visibility for `open`.
    if (this.shadowRoot.childElementCount === 0) return;
    if (name === "heading" && this._title) {
      this._title.textContent = this.heading;
    } else if (name === "open") {
      this._reflectOpen(oldValue !== null, newValue !== null);
    }
  }

  get heading() {
    return this.getAttribute("heading") || "";
  }

  set heading(v) {
    if (v == null) this.removeAttribute("heading");
    else this.setAttribute("heading", String(v));
  }

  get open() {
    return this.hasAttribute("open");
  }

  set open(v) {
    if (v) this.setAttribute("open", "");
    else this.removeAttribute("open");
  }

  show() {
    this.open = true;
  }

  hide(reason = "api") {
    if (!this.open) return;
    this._closeReason = reason;
    this.open = false;
  }

  toggle() {
    this.open ? this.hide() : this.show();
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          --am-accent: #0b5fff;
          --am-border: #d0d7de;
          --am-radius: 8px;
          font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
          color: #1f2328;
          box-sizing: border-box;
        }
        * { box-sizing: border-box; }
        .backdrop {
          position: fixed;
          inset: 0;
          display: none;
          align-items: center;
          justify-content: center;
          padding: 24px;
          background: rgba(31, 35, 40, 0.45);
          z-index: 1000;
        }
        :host([open]) .backdrop { display: flex; }
        .dialog {
          background: #fff;
          border: 1px solid var(--am-border);
          border-radius: var(--am-radius);
          box-shadow: 0 12px 32px rgba(31, 35, 40, 0.25);
          width: 100%;
          max-width: 480px;
          max-height: calc(100vh - 48px);
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }
        .header {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 14px 16px;
          border-bottom: 1px solid var(--am-border);
        }
        .title {
          margin: 0;
          font-size: 1rem;
          font-weight: 600;
          flex: 1;
          min-width: 0;
          overflow-wrap: break-word;
        }
        .close {
          flex: 0 0 auto;
          border: none;
          background: transparent;
          color: #57606a;
          font-size: 1.25rem;
          line-height: 1;
          width: 28px;
          height: 28px;
          border-radius: var(--am-radius);
          cursor: pointer;
        }
        .close:hover { background: #eaeef2; color: #1f2328; }
        .close:focus-visible { outline: 2px solid var(--am-accent); }
        .body {
          padding: 16px;
          overflow: auto;
          font-size: 0.9rem;
          line-height: 1.5;
        }
      </style>
      <div class="backdrop" part="backdrop">
        <div class="dialog" part="dialog" role="dialog" aria-modal="true"
          aria-labelledby="am-title">
          <div class="header" part="header">
            <h2 class="title" part="title" id="am-title">
              <slot name="heading">${this._escape(this.heading)}</slot>
            </h2>
            <button type="button" class="close" part="close"
              aria-label="Close">&times;</button>
          </div>
          <div class="body" part="body">
            <slot></slot>
          </div>
        </div>
      </div>
    `;

    this._backdrop = this.shadowRoot.querySelector(".backdrop");
    this._dialog = this.shadowRoot.querySelector(".dialog");
    this._title = this.shadowRoot.querySelector(".title");
    this._closeBtn = this.shadowRoot.querySelector(".close");

    this._closeBtn.addEventListener("click", () => this.hide("close-button"));
    this._backdrop.addEventListener("click", this._onBackdrop);
  }

  _escape(text) {
    return String(text).replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }

  _onBackdrop(ev) {
    // Only a click on the backdrop itself (not the dialog) closes it.
    if (ev.target === this._backdrop && !this.hasAttribute("no-backdrop-close")) {
      this.hide("backdrop");
    }
  }

  _onKeydown(ev) {
    if (ev.key === "Escape" && this.open) {
      ev.stopPropagation();
      this.hide("escape");
    }
  }

  _reflectOpen(wasOpen, isOpen) {
    if (isOpen === wasOpen) return;
    if (isOpen) {
      this.dispatchEvent(
        new CustomEvent("modal-open", { bubbles: true, composed: true })
      );
      // Move focus into the dialog for accessibility.
      if (this._closeBtn) this._closeBtn.focus();
    } else {
      const reason = this._closeReason || "api";
      this._closeReason = null;
      this.dispatchEvent(
        new CustomEvent("modal-close", {
          detail: { reason },
          bubbles: true,
          composed: true,
        })
      );
    }
  }
}

customElements.define("app-modal", AppModal);
