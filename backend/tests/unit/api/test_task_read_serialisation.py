"""Unit tests for rendering a task read model onto the REST surface.

The read model is assembled in the domain and rendered here, and the rendering
is a pure function over it — no request, no connection, no service — so it is
asserted directly rather than through a client. That is the whole reason it
lives in ``schemas.py`` beside the models it produces instead of inside a
controller.

Three properties are load-bearing rather than incidental.

**The read resource is a superset of the write one.** Create, ``PATCH`` and
retarget all answer with ``text``, ``status``, both anchor ids and
``intermediate_journal_ids``; the read adds the resolved journals, the contacts
and the lapse on top rather than replacing them. A client that already renders a
written task must not have to special-case the one it read back.

**``lapsed`` and ``lapse_reason`` travel together.** The model defines the flag
as "there is a reason", so a payload carrying one without the other would be a
second definition of lapsed sitting on the wire, and the two could disagree.

**A journal ref carries a date, not an instant.** The lapse verdict was reached
in the acting user's timezone; sending a timestamp would let a browser re-derive
the date in its own zone and disagree with the verdict it was sent alongside.

The separate file, rather than more of ``test_task_schemas.py``: that file pins
what a client may *send*, and this pins what it is *given*. They fail for
different reasons and the request file is long enough already.
"""

from __future__ import annotations

import datetime

import pytest
from core_shared.models.tasks import (
    JournalTaskGroups,
    LapseReason,
    Task,
    TaskContactRef,
    TaskJournalRef,
    TaskLinkRole,
    TaskReadModel,
    TaskStatus,
    UpcomingTasks,
    upcoming_window,
)

from app.api.tasks.schemas import (
    to_journal_tasks_response,
    to_task_read_resource,
    to_upcoming_tasks_response,
)

USER_ID = "test-user-123"
TASK_ID = 7
JOURNAL_ID = 100
DUE_JOURNAL_ID = 200
MENTIONED_JOURNAL_ID = 300

DUE_DATE = datetime.date(2026, 8, 20)


def journal_ref(
    journal_id: int,
    *,
    title: str = "Permit Meeting",
    date: datetime.date = DUE_DATE,
    cancelled: bool = False,
) -> TaskJournalRef:
    """A journal as the read model carries it."""
    return TaskJournalRef(id=journal_id, title=title, date=date, cancelled=cancelled)


def read_model(
    task_id: int = TASK_ID,
    *,
    creating_journal_id: int = JOURNAL_ID,
    due_journal_id: int = DUE_JOURNAL_ID,
    mentions: tuple[TaskJournalRef, ...] = (),
    contacts: tuple[TaskContactRef, ...] = (),
    lapse_reason: LapseReason | None = None,
    status: TaskStatus = TaskStatus.NOT_DONE,
) -> TaskReadModel:
    """An assembled read model, as a controller receives one."""
    return TaskReadModel(
        task=Task(
            id=task_id,
            user_id=USER_ID,
            text="return Sarah's book",
            creating_journal_id=creating_journal_id,
            due_journal_id=due_journal_id,
            status=status,
            created_at=datetime.datetime(2026, 8, 1, 9, 0, tzinfo=datetime.UTC),
            updated_at=datetime.datetime(2026, 8, 2, 9, 0, tzinfo=datetime.UTC),
        ),
        creating_journal=journal_ref(
            creating_journal_id, title="Monday Planning", date=datetime.date(2026, 8, 1)
        ),
        due_journal=journal_ref(due_journal_id),
        intermediate_journals=mentions,
        contacts=contacts,
        lapse_reason=lapse_reason,
    )


@pytest.mark.unit
class TestTheReadResourceIsASupersetOfTheWrittenOne:
    """Everything a written task carries, the read one carries too."""

    def test_the_scalar_attributes_survive_unchanged(self) -> None:
        """One renderer for the resource, whichever route produced it."""
        resource = to_task_read_resource(read_model())

        assert resource.type == "tasks"
        assert resource.id == str(TASK_ID)
        assert resource.attributes.text == "return Sarah's book"
        assert resource.attributes.status is TaskStatus.NOT_DONE
        assert resource.attributes.creating_journal_id == JOURNAL_ID
        assert resource.attributes.due_journal_id == DUE_JOURNAL_ID

    def test_the_trail_is_still_present_as_ids(self) -> None:
        """``intermediate_journal_ids`` stays, beside the resolved journals.

        Dropping it in favour of the objects would break a client written
        against the create and ``PATCH`` responses, which is precisely the
        special-casing the superset avoids.
        """
        resource = to_task_read_resource(
            read_model(mentions=(journal_ref(MENTIONED_JOURNAL_ID),))
        )

        assert resource.attributes.intermediate_journal_ids == [MENTIONED_JOURNAL_ID]

    def test_the_timestamps_survive_unchanged(self) -> None:
        """Created and updated are the task's own, not the read's."""
        resource = to_task_read_resource(read_model())

        assert resource.attributes.created_at == datetime.datetime(
            2026, 8, 1, 9, 0, tzinfo=datetime.UTC
        )
        assert resource.attributes.updated_at == datetime.datetime(
            2026, 8, 2, 9, 0, tzinfo=datetime.UTC
        )

    def test_the_resource_carries_a_self_link(self) -> None:
        """The link the write responses withheld until a read existed."""
        resource = to_task_read_resource(read_model(), "https://pms.test")

        assert resource.links is not None
        assert resource.links.self == f"https://pms.test/api/tasks/{TASK_ID}"

    def test_the_self_link_is_absolute_like_every_other_resource(self) -> None:
        """``base_url`` is a parameter, so the renderer stays pure.

        Every other ``links.self`` in this API is base-URL prefixed, and a
        client that resolves ``self`` uniformly across resource types would
        otherwise get two different shapes from the same API.
        """
        listed = to_journal_tasks_response(
            JournalTaskGroups(
                journal_id=JOURNAL_ID,
                due=(read_model(1),),
                created=(),
                mentioned=(),
            ),
            "https://pms.test",
        )

        assert listed.data[0].links is not None
        assert listed.data[0].links.self == "https://pms.test/api/tasks/1"


@pytest.mark.unit
class TestAnUnpersistedTaskIsRefused:
    """A task with no id cannot be rendered, on either surface.

    ``task.id or 0`` would have produced a resource identifying itself two
    ways — ``id="None"`` beside a ``self`` link ending ``/api/tasks/0`` — which
    is a task that cannot exist. Unreachable through the service, which renders
    only what a repository handed back, so it fails loudly instead, as
    ``ContactConverter._validate_entity_id`` does.
    """

    def unpersisted(self) -> TaskReadModel:
        """A read model whose task was never saved."""
        model = read_model()
        return TaskReadModel(
            task=Task(
                user_id=USER_ID,
                text=model.task.text,
                creating_journal_id=JOURNAL_ID,
                due_journal_id=DUE_JOURNAL_ID,
                status=TaskStatus.NOT_DONE,
            ),
            creating_journal=model.creating_journal,
            due_journal=model.due_journal,
            intermediate_journals=(),
            contacts=(),
            lapse_reason=None,
        )

    def test_the_single_read_refuses_it(self) -> None:
        """Rather than emitting ``id="None"`` and a link to task 0."""
        with pytest.raises(ValueError, match="persisted"):
            to_task_read_resource(self.unpersisted())

    def test_the_listing_refuses_it(self) -> None:
        """The same guard on the row renderer."""
        groups = JournalTaskGroups(
            journal_id=JOURNAL_ID,
            due=(self.unpersisted(),),
            created=(),
            mentioned=(),
        )

        with pytest.raises(ValueError, match="persisted"):
            to_journal_tasks_response(groups)


@pytest.mark.unit
class TestJournalsByRole:
    """The three roles, resolved rather than left as ids."""

    def test_both_anchors_are_rendered_with_title_and_date(self) -> None:
        """Enough to render a link without a second request."""
        resource = to_task_read_resource(read_model())

        assert resource.attributes.creating_journal.id == JOURNAL_ID
        assert resource.attributes.creating_journal.title == "Monday Planning"
        assert resource.attributes.due_journal.title == "Permit Meeting"

    def test_a_journal_ref_carries_a_date_rather_than_an_instant(self) -> None:
        """The date the lapse rule judged, not one a browser can re-derive."""
        resource = to_task_read_resource(read_model())

        assert resource.attributes.due_journal.date == DUE_DATE
        assert not isinstance(resource.attributes.due_journal.date, datetime.datetime)

    def test_a_cancelled_journal_is_marked_wherever_it_appears(self) -> None:
        """The flag rides on the ref, so any surface showing one can mark it."""
        model = TaskReadModel(
            task=read_model().task,
            creating_journal=journal_ref(JOURNAL_ID),
            due_journal=journal_ref(DUE_JOURNAL_ID, cancelled=True),
            intermediate_journals=(),
            contacts=(),
            lapse_reason=LapseReason.DUE_JOURNAL_CANCELLED,
        )

        resource = to_task_read_resource(model)

        assert resource.attributes.due_journal.cancelled is True
        assert resource.attributes.creating_journal.cancelled is False

    def test_mentions_are_rendered_in_the_order_the_model_holds_them(self) -> None:
        """Ordering is the domain's decision; the renderer does not re-sort."""
        model = read_model(
            mentions=(
                journal_ref(MENTIONED_JOURNAL_ID, title="Second"),
                journal_ref(MENTIONED_JOURNAL_ID + 1, title="First"),
            )
        )

        resource = to_task_read_resource(model)

        assert [ref.title for ref in resource.attributes.intermediate_journals] == [
            "Second",
            "First",
        ]

    def test_a_task_with_no_mentions_renders_an_empty_list(self) -> None:
        """Empty rather than absent, so a client needs no null check."""
        resource = to_task_read_resource(read_model())

        assert resource.attributes.intermediate_journals == []


@pytest.mark.unit
class TestContacts:
    """A plain reference, and nothing more."""

    def test_contacts_carry_a_display_name_and_a_photo(self) -> None:
        """What a row needs to show a person."""
        resource = to_task_read_resource(
            read_model(
                contacts=(
                    TaskContactRef(
                        id=5,
                        display_name="Sarah Chen",
                        photo_url="https://example.test/s.jpg",
                    ),
                )
            )
        )

        (contact,) = resource.attributes.contacts
        assert contact.id == 5
        assert contact.display_name == "Sarah Chen"
        assert contact.photo_url == "https://example.test/s.jpg"

    def test_a_contact_without_a_photo_renders_null(self) -> None:
        """Absent rather than invented."""
        resource = to_task_read_resource(
            read_model(
                contacts=(
                    TaskContactRef(id=5, display_name="Sarah Chen", photo_url=None),
                )
            )
        )

        assert resource.attributes.contacts[0].photo_url is None

    def test_the_link_carries_no_role_or_attendance(self) -> None:
        """The specification calls it a plain reference, so the payload is one."""
        resource = to_task_read_resource(
            read_model(
                contacts=(
                    TaskContactRef(id=5, display_name="Sarah Chen", photo_url=None),
                )
            )
        )

        assert set(resource.attributes.contacts[0].model_dump()) == {
            "id",
            "display_name",
            "photo_url",
        }


@pytest.mark.unit
class TestTheLapse:
    """The flag and the reason, which must never disagree."""

    def test_a_task_that_has_not_lapsed_says_so_and_carries_no_reason(self) -> None:
        """``null`` rather than an omitted key: absent reads as unknown."""
        resource = to_task_read_resource(read_model())

        assert resource.attributes.lapsed is False
        assert resource.attributes.lapse_reason is None
        assert "lapse_reason" in resource.attributes.model_dump()

    @pytest.mark.parametrize(
        ("reason", "wire_value"),
        [
            (LapseReason.DATE_PASSED, "date_passed"),
            (LapseReason.DUE_JOURNAL_CANCELLED, "due_journal_cancelled"),
        ],
    )
    def test_a_lapsed_task_carries_the_reason_as_structured_data(
        self, reason: LapseReason, wire_value: str
    ) -> None:
        """The two causes ask the user for different things, so both reach it.

        Structured rather than pre-worded, which is what lets the UI phrase
        them distinctly — including for a screen reader — instead of inferring
        a cause from a boolean.
        """
        resource = to_task_read_resource(read_model(lapse_reason=reason))

        assert resource.attributes.lapsed is True
        assert resource.attributes.lapse_reason is reason
        assert resource.attributes.model_dump(mode="json")["lapse_reason"] == wire_value

    @pytest.mark.parametrize(
        "reason",
        [None, LapseReason.DATE_PASSED, LapseReason.DUE_JOURNAL_CANCELLED],
    )
    def test_the_flag_and_the_reason_always_agree_on_the_wire(
        self, reason: LapseReason | None
    ) -> None:
        """Both fields are always present, and they never contradict each other.

        The model defines ``lapsed`` as "there is a reason", so a payload
        carrying one without the other would be a second definition of lapsed
        sitting on the wire. Asserted on the **rendered** payload across all
        three cases, because a renderer that dropped either field — or emitted a
        `lapsed` derived some other way — is what this is guarding against.
        """
        payload = to_task_read_resource(
            read_model(lapse_reason=reason)
        ).attributes.model_dump(mode="json")

        assert set(payload) >= {"lapsed", "lapse_reason"}
        assert payload["lapsed"] is (reason is not None)
        assert payload["lapse_reason"] == (str(reason) if reason else None)


@pytest.mark.unit
class TestTheJournalListingEnvelope:
    """Each task once in ``data``, with the roles beside it and in ``meta``."""

    def two_role_groups(self) -> JournalTaskGroups:
        """A journal holding one task in two roles and one in a third."""
        both = read_model(1, creating_journal_id=JOURNAL_ID, due_journal_id=JOURNAL_ID)
        mentioned = read_model(
            2,
            creating_journal_id=DUE_JOURNAL_ID,
            due_journal_id=DUE_JOURNAL_ID,
            mentions=(journal_ref(JOURNAL_ID),),
        )
        return JournalTaskGroups(
            journal_id=JOURNAL_ID,
            due=(both,),
            created=(both,),
            mentioned=(mentioned,),
        )

    def test_a_two_role_task_appears_once_in_data(self) -> None:
        """JSON:API forbids the same resource twice in ``data``.

        Which is why the roles are an attribute here rather than the structure
        the collection is nested under — the MCP tool, with no such rule, nests.
        """
        response = to_journal_tasks_response(self.two_role_groups())

        assert [resource.id for resource in response.data] == ["1", "2"]

    def test_each_resource_names_every_role_it_holds(self) -> None:
        """Both roles, so a client can place the row in both groups itself."""
        response = to_journal_tasks_response(self.two_role_groups())
        by_id = {resource.id: resource for resource in response.data}

        assert by_id["1"].attributes.link_roles == [
            TaskLinkRole.DUE,
            TaskLinkRole.CREATED,
        ]
        assert by_id["2"].attributes.link_roles == [TaskLinkRole.MENTIONED]

    def test_the_meta_carries_the_ordered_ids_per_group(self) -> None:
        """The grouping the acceptance criterion asks for, stated explicitly."""
        response = to_journal_tasks_response(self.two_role_groups())

        assert response.meta.groups.due == [1]
        assert response.meta.groups.created == [1]
        assert response.meta.groups.mentioned == [2]

    def test_an_empty_journal_renders_empty_data_and_empty_groups(self) -> None:
        """A journal with no tasks is a normal answer with a normal shape."""
        response = to_journal_tasks_response(
            JournalTaskGroups(journal_id=JOURNAL_ID, due=(), created=(), mentioned=())
        )

        assert response.data == []
        assert response.meta.groups.due == []
        assert response.meta.groups.created == []
        assert response.meta.groups.mentioned == []

    def test_a_filtered_listing_keeps_the_same_shape(self) -> None:
        """The other groups are empty, not missing.

        A client parses one answer whether or not it asked for a role.
        """
        groups = self.two_role_groups()
        filtered = JournalTaskGroups(
            journal_id=groups.journal_id,
            due=groups.due,
            created=(),
            mentioned=(),
        )

        response = to_journal_tasks_response(filtered)

        assert [resource.id for resource in response.data] == ["1"]
        assert response.meta.groups.created == []
        assert response.data[0].attributes.link_roles == [TaskLinkRole.DUE]

    def test_the_listed_resources_carry_the_full_read_attributes(self) -> None:
        """A row on a journal shows the task, its contacts and its lapse.

        The listing is not a thinner projection of the read model: the
        specification asks a journal's tasks for "the task text, its status,
        its linked contacts, and — for lapsed tasks — a clear lapsed marker",
        which is the read model entire.
        """
        response = to_journal_tasks_response(self.two_role_groups())

        attributes = response.data[0].attributes
        assert attributes.text == "return Sarah's book"
        assert attributes.due_journal.id == JOURNAL_ID
        assert attributes.lapsed is False
        assert attributes.contacts == []


@pytest.mark.unit
class TestTheUpcomingWindowEnvelope:
    """The dashboard's listing: the read shape, plus the window it covers.

    A different envelope from a journal's listing, and deliberately so. That one
    is *about a journal* and reports a grouping; this one is about a **window**,
    which no row carries, so the window rides in ``meta`` — and must be there
    even when there are no rows to infer it from.
    """

    def upcoming(self, *models: TaskReadModel, days_ahead: int = 7) -> UpcomingTasks:
        """An assembled answer, as a controller receives one."""
        window = upcoming_window(datetime.date(2026, 8, 11), days_ahead)
        return UpcomingTasks(window=window, tasks=models)

    def test_the_rows_carry_the_full_read_attributes(self) -> None:
        """The same shape ``GET /api/tasks/{id}`` returns, not a thinner one.

        The specification asks each dashboard entry for "the task text, the due
        journal's title and date, and any linked contacts" — all of which the
        read resource already carries, so the row *is* the read resource rather
        than a projection that could drift from it.
        """
        response = to_upcoming_tasks_response(
            self.upcoming(read_model(contacts=(TaskContactRef(1, "Sarah Chen", None),)))
        )

        attributes = response.data[0].attributes
        assert attributes.text == "return Sarah's book"
        assert attributes.due_journal.title == "Permit Meeting"
        assert attributes.due_journal.date == DUE_DATE
        assert [contact.display_name for contact in attributes.contacts] == [
            "Sarah Chen"
        ]

    def test_each_row_carries_an_absolute_self_link(self) -> None:
        """The same link shape every other task response emits."""
        response = to_upcoming_tasks_response(
            self.upcoming(read_model()), "https://pms.test"
        )

        assert response.data[0].links is not None
        assert response.data[0].links.self == f"https://pms.test/api/tasks/{TASK_ID}"

    def test_the_meta_names_the_window(self) -> None:
        """A surface renders "the next seven days", so it is told which days."""
        response = to_upcoming_tasks_response(self.upcoming(read_model()))

        assert response.meta.window.start_date == datetime.date(2026, 8, 11)
        assert response.meta.window.end_date == datetime.date(2026, 8, 18)
        assert response.meta.window.days_ahead == 7

    def test_the_meta_names_the_total(self) -> None:
        """What the dashboard's show-more counts.

        Equal to ``len(data)`` because the window is uncapped — the whole window
        travels and the five-item cap is the UI's — so this is the full count
        rather than a page's.
        """
        response = to_upcoming_tasks_response(
            self.upcoming(read_model(1), read_model(2))
        )

        assert response.meta.total == 2 == len(response.data)

    def test_an_empty_window_still_names_its_dates(self) -> None:
        """The case the rows could not have told a client about.

        "Nothing due between today and next Tuesday" is the empty state, and a
        response that dropped the window when it dropped the rows could not say
        it.
        """
        response = to_upcoming_tasks_response(self.upcoming(days_ahead=3))

        assert response.data == []
        assert response.meta.total == 0
        assert response.meta.window.end_date == datetime.date(2026, 8, 14)

    def test_the_row_order_is_preserved(self) -> None:
        """The rule ordered them; the renderer must not reshuffle."""
        response = to_upcoming_tasks_response(
            self.upcoming(read_model(3), read_model(1), read_model(2))
        )

        assert [resource.id for resource in response.data] == ["3", "1", "2"]

    def test_an_unpersisted_task_is_refused(self) -> None:
        """The same guard the other two surfaces carry.

        A row silently dropped from a dashboard is worse than an error: the
        caller cannot tell it was dropped.
        """
        unpersisted = TaskReadModel(
            task=Task(
                user_id=USER_ID,
                text="unsaved",
                creating_journal_id=JOURNAL_ID,
                due_journal_id=DUE_JOURNAL_ID,
                status=TaskStatus.NOT_DONE,
            ),
            creating_journal=journal_ref(JOURNAL_ID),
            due_journal=journal_ref(DUE_JOURNAL_ID),
            intermediate_journals=(),
            contacts=(),
            lapse_reason=None,
        )

        with pytest.raises(ValueError, match="persisted"):
            to_upcoming_tasks_response(self.upcoming(unpersisted))
