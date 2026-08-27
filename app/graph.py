from langchain_core.messages import SystemMessage, HumanMessage

from app.prompts.noc_system import NOC_SYSTEM_PROMPT
from app.prompts.incident import build_incident_prompt
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from app.state import NOCState
from app.llm import get_llm

from app.tools.telemetry import get_site_telemetry
from app.tools.alarms import get_site_alarms
from app.tools.inventory import get_network_path


tools = [
    get_site_telemetry,
    get_site_alarms,
    get_network_path,
]

llm = get_llm()
llm_with_tools = llm.bind_tools(tools)


def call_llm(state: NOCState):

    messages = state.get("messages", [])

    if not messages:
        incident_prompt = build_incident_prompt(
            incident_id=state["incident_id"],
            site=state["site"],
            technology=state["technology"],
            severity=state["severity"],
            description=state["description"],
        )

        messages = [
            SystemMessage(content=NOC_SYSTEM_PROMPT),
            HumanMessage(content=incident_prompt),
        ]

    response = llm_with_tools.invoke(messages)

    return {
        "messages": messages + [response]
    }



tool_node = ToolNode(tools)


def should_continue(state: NOCState):

    last_message = state["messages"][-1]

    if last_message.tool_calls:
        return "tools"

    return END


def build_graph():

    builder = StateGraph(NOCState)

    builder.add_node("agent", call_llm)
    builder.add_node("tools", tool_node)

    builder.add_edge(START, "agent")

    builder.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            END: END,
        },
    )

    builder.add_edge("tools", "agent")

    return builder.compile()

