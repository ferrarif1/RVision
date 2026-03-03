"""Compatibility exports for audit actions.

Keep the original import style (`from app.audit import actions`) while sourcing
all values from `app.core.constants`.
"""

from app.core.constants import AUDIT_ACTION_ASSET_UPLOAD as ASSET_UPLOAD
from app.core.constants import AUDIT_ACTION_EDGE_PULL_MODEL as EDGE_PULL_MODEL
from app.core.constants import AUDIT_ACTION_EDGE_PULL_TASKS as EDGE_PULL_TASKS
from app.core.constants import AUDIT_ACTION_EDGE_PUSH_RESULTS as EDGE_PUSH_RESULTS
from app.core.constants import AUDIT_ACTION_LOGIN as LOGIN
from app.core.constants import AUDIT_ACTION_MODEL_APPROVE as MODEL_APPROVE
from app.core.constants import AUDIT_ACTION_MODEL_DOWNLOAD as MODEL_DOWNLOAD
from app.core.constants import AUDIT_ACTION_MODEL_REGISTER as MODEL_REGISTER
from app.core.constants import AUDIT_ACTION_MODEL_RECOMMEND as MODEL_RECOMMEND
from app.core.constants import AUDIT_ACTION_MODEL_RELEASE as MODEL_RELEASE
from app.core.constants import AUDIT_ACTION_MODEL_SUBMIT as MODEL_SUBMIT
from app.core.constants import AUDIT_ACTION_ORCHESTRATOR_RUN as ORCHESTRATOR_RUN
from app.core.constants import AUDIT_ACTION_PIPELINE_REGISTER as PIPELINE_REGISTER
from app.core.constants import AUDIT_ACTION_PIPELINE_RELEASE as PIPELINE_RELEASE
from app.core.constants import AUDIT_ACTION_REVIEW_QUEUE_ENQUEUE as REVIEW_QUEUE_ENQUEUE
from app.core.constants import AUDIT_ACTION_RESULT_EXPORT as RESULT_EXPORT
from app.core.constants import AUDIT_ACTION_TASK_CREATE as TASK_CREATE
from app.core.constants import AUDIT_ACTION_TASK_DELETE as TASK_DELETE
from app.core.constants import AUDIT_ACTION_TASK_ROUTE as TASK_ROUTE

ALL_AUDIT_ACTIONS = (
    LOGIN,
    ASSET_UPLOAD,
    TASK_CREATE,
    MODEL_SUBMIT,
    MODEL_APPROVE,
    MODEL_REGISTER,
    MODEL_RELEASE,
    MODEL_DOWNLOAD,
    MODEL_RECOMMEND,
    RESULT_EXPORT,
    TASK_DELETE,
    TASK_ROUTE,
    PIPELINE_REGISTER,
    PIPELINE_RELEASE,
    ORCHESTRATOR_RUN,
    REVIEW_QUEUE_ENQUEUE,
    EDGE_PULL_TASKS,
    EDGE_PULL_MODEL,
    EDGE_PUSH_RESULTS,
)
