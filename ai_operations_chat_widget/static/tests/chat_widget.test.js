/** @odoo-module **/

import { expect, test, describe } from "@odoo/hoot";
import { click, queryAll, queryFirst } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    defineModels,
    fields,
    models,
    mountWithCleanup,
    onRpc,
} from "@web/../tests/web_test_helpers";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { AiOperationsChatWidget } from "@ai_operations_chat_widget/chat_widget";

describe.current.tags("desktop");

/**
 * The component RPCs against ai.operations.agent.profile, and the webclient
 * environment it mounts into reaches for the mail models. Both have to exist in
 * the mock server or every test fails on "could not get model from server
 * environment" -- which is exactly what happened the first time these were run.
 */
class AiOperationsAgentProfile extends models.Model {
    _name = "ai.operations.agent.profile";

    name = fields.Char();
    code = fields.Char();
}

defineMailModels();
defineModels([AiOperationsAgentProfile]);

const TWO_PROFILES = [
    { id: 1, name: "Procurement Intelligence", code: "procurement" },
    { id: 2, name: "Manufacturing Intelligence", code: "manufacturing" },
];

function mockProfiles(profiles) {
    onRpc("ai.operations.agent.profile", "ai_widget_profiles", () => profiles);
}

test("no launcher when the user may talk to no agent", async () => {
    mockProfiles([]);
    await mountWithCleanup(AiOperationsChatWidget);
    expect(".o_ai_chat_launcher").toHaveCount(0);
});

test("the launcher renders when the user has an agent", async () => {
    mockProfiles(TWO_PROFILES);
    await mountWithCleanup(AiOperationsChatWidget);
    expect(".o_ai_chat_launcher").toHaveCount(1);
    expect(".o_ai_chat_panel").toHaveCount(0);
});

test("clicking the launcher opens and closes the panel", async () => {
    mockProfiles(TWO_PROFILES);
    await mountWithCleanup(AiOperationsChatWidget);

    await click(".o_ai_chat_launcher");
    await animationFrame();
    expect(".o_ai_chat_panel").toHaveCount(1);

    await click(".o_ai_chat_icon");
    await animationFrame();
    expect(".o_ai_chat_panel").toHaveCount(0);
});

test("the agent selector offers every profile the server returned", async () => {
    mockProfiles(TWO_PROFILES);
    await mountWithCleanup(AiOperationsChatWidget);
    await click(".o_ai_chat_launcher");
    await animationFrame();
    expect(queryAll(".o_ai_chat_agent option")).toHaveLength(2);
});

test("a single profile needs no selector", async () => {
    mockProfiles([TWO_PROFILES[0]]);
    await mountWithCleanup(AiOperationsChatWidget);
    await click(".o_ai_chat_launcher");
    await animationFrame();
    expect(".o_ai_chat_agent").toHaveCount(0);
});

test("sending a message renders the question and the answer", async () => {
    mockProfiles(TWO_PROFILES);
    onRpc("ai.operations.agent.profile", "ai_widget_send", () => ({
        channel_id: 7, profile_id: 1, reply: "You have one open order.",
    }));
    const widget = await mountWithCleanup(AiOperationsChatWidget);

    await click(".o_ai_chat_launcher");
    await animationFrame();
    widget.state.draft = "list my open purchase orders";
    await widget.send();
    await animationFrame();

    expect(".o_ai_chat_user").toHaveCount(1);
    expect(queryFirst(".o_ai_chat_user")).toHaveText("list my open purchase orders");
    expect(queryFirst(".o_ai_chat_message.o_ai_chat_agent")).toHaveText(
        "You have one open order."
    );
});

test("a second send is refused while one is in flight", async () => {
    mockProfiles(TWO_PROFILES);
    let calls = 0;
    onRpc("ai.operations.agent.profile", "ai_widget_send", () => {
        calls++;
        return { channel_id: 7, profile_id: 1, reply: "ok" };
    });
    const widget = await mountWithCleanup(AiOperationsChatWidget);

    widget.state.sending = true;            // a run is already in flight
    widget.state.draft = "second question";
    await widget.send();

    expect(calls).toBe(0);
    expect(widget.state.draft).toBe("second question");
});

test("a server failure answers with a neutral sentence, never a traceback", async () => {
    mockProfiles(TWO_PROFILES);
    onRpc("ai.operations.agent.profile", "ai_widget_send", () => {
        throw new Error("RPC_ERROR: something internal");
    });
    const widget = await mountWithCleanup(AiOperationsChatWidget);

    widget.state.draft = "hello";
    await widget.send();
    await animationFrame();

    const reply = queryFirst(".o_ai_chat_message.o_ai_chat_agent").textContent;
    expect(reply).not.toInclude("RPC_ERROR");
    expect(reply).not.toInclude("internal");
});

test("switching agent does not carry the transcript across", async () => {
    mockProfiles(TWO_PROFILES);
    const widget = await mountWithCleanup(AiOperationsChatWidget);
    widget.state.messages = [{ author: "user", body: "about procurement" }];
    widget.state.channelId = 7;

    widget.onSelectProfile({ target: { value: "2" } });

    expect(widget.state.messages).toHaveLength(0);
    expect(widget.state.channelId).toBe(null);
});
