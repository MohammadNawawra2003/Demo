/** @odoo-module **/

import { Component, onWillStart, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * A launcher fixed to the bottom-right of the backend, and the compact panel it
 * opens.
 *
 * The component holds no security decision. It asks the server which agents the
 * user may talk to and it posts messages; every answer to "may I" comes from
 * the ORM, which applies the same record rules the rest of Odoo applies. There
 * is no provider call here, no key, and no tool name: the browser never learns
 * that a vendor exists.
 */

/** Current app -> agent profile code. Only a preselection; the user can change it. */
const APP_TO_PROFILE = {
    "purchase.menu_purchase_root": "procurement",
    "mrp.menu_mrp_root": "manufacturing",
    "stock.menu_stock_root": "inventory",
    "quality_control.menu_quality_root": "quality",
    "quality.menu_quality_root": "quality",
};

export class AiOperationsChatWidget extends Component {
    static template = "ai_operations_chat_widget.ChatWidget";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.menuService = useService("menu");
        this.actionService = useService("action");
        this.threadRef = useRef("thread");

        this.state = useState({
            available: false,
            open: false,
            sending: false,
            profiles: [],
            profileId: null,
            channelId: null,
            messages: [],
            draft: "",
        });

        onWillStart(async () => {
            let profiles = [];
            try {
                profiles = await this.orm.call(
                    "ai.operations.agent.profile", "ai_widget_profiles", []
                );
            } catch {
                profiles = [];          // never break the webclient over a launcher
            }
            this.state.profiles = profiles;
            // No profiles means no launcher. A user who cannot run a tool should
            // not be offered a box that will refuse every message.
            this.state.available = profiles.length > 0;
            this.state.profileId = this._preselect(profiles);
        });
    }

    _preselect(profiles) {
        if (!profiles.length) {
            return null;
        }
        const currentApp = this.menuService.getCurrentApp && this.menuService.getCurrentApp();
        const wanted = currentApp && APP_TO_PROFILE[currentApp.xmlid];
        const match = wanted && profiles.find((profile) => profile.code === wanted);
        return (match || profiles[0]).id;
    }

    get activeProfile() {
        return this.state.profiles.find((p) => p.id === this.state.profileId) || null;
    }

    toggle() {
        this.state.open = !this.state.open;
    }

    close() {
        this.state.open = false;
    }

    onSelectProfile(ev) {
        const profileId = Number(ev.target.value);
        if (profileId !== this.state.profileId) {
            this.state.profileId = profileId;
            // A conversation belongs to one agent. Switching agent switches
            // conversation rather than carrying the transcript across.
            this.state.messages = [];
            this.state.channelId = null;
        }
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.send();
        }
    }

    async send() {
        const body = (this.state.draft || "").trim();
        // One request at a time: a second send would open a second run against
        // the same conversation, which the server refuses anyway.
        if (!body || this.state.sending || !this.state.profileId) {
            return;
        }
        this.state.draft = "";
        this.state.messages.push({ author: "user", body });
        this.state.sending = true;
        this._scroll();

        let reply;
        try {
            const result = await this.orm.call(
                "ai.operations.agent.profile", "ai_widget_send",
                [[this.state.profileId], body]
            );
            this.state.channelId = result.channel_id;
            reply = result.reply;
        } catch {
            // Whatever went wrong, the user gets a sentence. The reason lives in
            // the audit log, where it belongs.
            reply = _t("I am unavailable right now. Nothing has been changed.");
        } finally {
            this.state.sending = false;
        }
        this.state.messages.push({ author: "agent", body: reply });
        this._scroll();
    }

    _scroll() {
        Promise.resolve().then(() => {
            const thread = this.threadRef.el;
            if (thread) {
                thread.scrollTop = thread.scrollHeight;
            }
        });
    }

    openInDiscuss() {
        if (!this.state.channelId) {
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.client",
            tag: "mail.action_discuss",
            params: { channel_id: this.state.channelId },
        });
        this.close();
    }
}

registry.category("main_components").add("ai_operations_chat_widget.ChatWidget", {
    Component: AiOperationsChatWidget,
});
