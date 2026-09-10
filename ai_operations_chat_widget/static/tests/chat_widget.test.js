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
    patchWithCleanup,
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
    // Opening the panel loads the conversation that already exists.
    onRpc("ai.operations.agent.profile", "ai_widget_open", () => ({
        channel_id: 7, profile_id: profiles[0] ? profiles[0].id : 1, messages: [],
    }));
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

    await click("button[aria-label='Close']");
    await animationFrame();
    expect(".o_ai_chat_panel").toHaveCount(0);
});

test("the agent selector offers every profile the server returned", async () => {
    mockProfiles(TWO_PROFILES);
    await mountWithCleanup(AiOperationsChatWidget);
    await click(".o_ai_chat_launcher");
    await animationFrame();
    expect(queryAll(".o_ai_chat_panel select option")).toHaveLength(2);
});

test("a single profile needs no selector", async () => {
    mockProfiles([TWO_PROFILES[0]]);
    await mountWithCleanup(AiOperationsChatWidget);
    await click(".o_ai_chat_launcher");
    await animationFrame();
    expect(".o_ai_chat_panel select").toHaveCount(0);
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

    expect(".o_ai_chat_row.justify-content-end").toHaveCount(1);
    expect(queryFirst(".o_ai_chat_row.justify-content-end .o_ai_chat_body")).toHaveText(
        "list my open purchase orders"
    );
    expect(queryFirst(".o_ai_chat_bubble_agent .o_ai_chat_body")).toHaveText(
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

    // The panel has to be open, or there is no DOM to assert against.
    await click(".o_ai_chat_launcher");
    await animationFrame();
    widget.state.draft = "hello";
    await widget.send();
    await animationFrame();

    const reply = queryFirst(".o_ai_chat_bubble_agent .o_ai_chat_body").textContent;
    expect(reply).not.toInclude("RPC_ERROR");
    expect(reply).not.toInclude("internal");
});

test("an image upload carries the CSRF token and holds the id Odoo 19 returns", async () => {
    // George's "That image could not be attached." was two defects in this
    // one call: Odoo 19's http.post no longer adds csrf_token, so the route
    // answered 400; and the reply is {data: {attachment_id, store_data}},
    // which the old parse read as data["ir.attachment"] and found nothing.
    mockProfiles(TWO_PROFILES);
    patchWithCleanup(odoo, { csrf_token: "the-csrf-token" });
    onRpc("/mail/attachment/upload", async (request) => {
        const body = await request.formData();
        expect.step(`csrf ${body.get("csrf_token")}`);
        expect.step(`thread ${body.get("thread_model")} ${body.get("thread_id")}`);
        return { data: { attachment_id: 42, store_data: { "ir.attachment": [{ id: 42 }] } } };
    });
    const widget = await mountWithCleanup(AiOperationsChatWidget);
    await click(".o_ai_chat_launcher");
    await animationFrame();

    const file = new File(["png"], "shapes.png", { type: "image/png" });
    await widget.onFileSelected({ target: { files: [file], value: "" } });

    expect.verifySteps(["csrf the-csrf-token", "thread discuss.channel 7"]);
    expect(widget.state.pending).toEqual({ id: 42, name: "shapes.png" });
    expect(widget.state.error).toBe(null);
});

test("each text takes its direction from its own content inside an RTL page", async () => {
    // The Arabic UI is RTL. An English sentence inheriting that direction
    // renders ".That image could not be attached" -- the screenshot.
    mockProfiles(TWO_PROFILES);
    const widget = await mountWithCleanup(AiOperationsChatWidget);
    queryFirst(".o_ai_chat_widget").setAttribute("dir", "rtl");
    await click(".o_ai_chat_launcher");
    await animationFrame();
    const direction = (selector) => getComputedStyle(queryFirst(selector)).direction;

    expect(direction(".o_ai_chat_thread > .text-muted")).toBe("ltr");

    widget.state.messages = [
        { id: 1, author: "user", body: "ما هي الفواتير المتأخرة؟" },
        { id: 2, author: "agent", body: "Refused: you may not do that." },
    ];
    widget.state.error = "That image could not be attached.";
    await animationFrame();

    const bodies = queryAll(".o_ai_chat_body");
    expect(getComputedStyle(bodies[0]).direction).toBe("rtl");
    expect(getComputedStyle(bodies[1]).direction).toBe("ltr");
    expect(direction(".o_ai_chat_panel .alert span")).toBe("ltr");
    // The page itself stays RTL: only content-bearing elements decide.
    expect(direction(".o_ai_chat_panel")).toBe("rtl");
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
