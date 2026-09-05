"""The kernel's own tools.

Only diagnostics live here. Every tool that touches the business lives in a
tool pack, because the kernel depends on ``base`` and ``mail`` and a tool
declaring ``purchase.order`` would drag ``purchase`` in behind it.
"""

from ..services.enums import AutonomyLevel, ToolCategory
from ..services.registry import ai_tool
from ..services.schema import Int, List, Schema, Str


class DescribeScopeInput(Schema):
    """No parameters: the answer is a property of the caller, not the request."""


class DescribeScopeOutput(Schema):
    profile_code = Str()
    execution_mode = Str()
    execution_user = Str()
    company_ids = List(Int())
    company_names = List(Str())
    max_autonomy_level = Int()


@ai_tool(
    code="core.describe_scope",
    category=ToolCategory.READ,
    autonomy=AutonomyLevel.QUERY,
    models=["res.company"],
    input_schema=DescribeScopeInput,
    output_schema=DescribeScopeOutput,
    max_results=1,
)
def describe_scope(ctx, params):
    """Report the scope this agent is executing under right now.

    Returns the agent's code, the identity it is running as, the companies it
    may currently see, and its autonomy ceiling. Use it to answer questions
    about what you can and cannot reach; it reveals nothing about any business
    record.
    """
    companies = ctx.model('res.company').browse(ctx.company_ids)
    return {
        'profile_code': ctx.profile.code,
        'execution_mode': str(getattr(ctx.execution_mode, 'value', ctx.execution_mode)),
        'execution_user': ctx.execution_user.name,
        'company_ids': list(ctx.company_ids),
        'company_names': companies.mapped('name'),
        'max_autonomy_level': int(ctx.autonomy),
    }
