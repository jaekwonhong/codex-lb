from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from threading import RLock

from app.modules.member_auth_handoff.repository import (
    CustomMemberAuthCatalogRecord,
    MemberAuthCatalogOverlayRepository,
)
from app.modules.member_auth_handoff.schemas import (
    CatalogMemberIdentity,
    CatalogMemberRegistrationRequest,
    CatalogMemberRegistrationResponse,
)

_MAX_MEMBERS_PER_WORKSPACE = 20


@dataclass(frozen=True, slots=True)
class MemberAuthHandoffCatalogEntry:
    preset_id: str
    workspace_id: str
    owner_email: str
    workspace_account_id: str
    email: str
    user_id: str


@dataclass(frozen=True, slots=True)
class MemberAuthHandoffCatalog:
    entries: tuple[MemberAuthHandoffCatalogEntry, ...]
    owner_entries: tuple[MemberAuthHandoffCatalogEntry, ...] = ()

    def fingerprint(self) -> str:
        canonical = "\n".join(
            sorted(
                f"{entry.preset_id}|{entry.workspace_id}|{entry.workspace_account_id}|"
                f"{entry.email.strip().casefold()}|{entry.user_id}"
                for entry in self.entries
            )
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    def find_target(
        self,
        *,
        preset_id: str,
        email: str,
        user_id: str,
    ) -> MemberAuthHandoffCatalogEntry | None:
        normalized_email = email.casefold()
        return next(
            (
                entry
                for entry in self.entries
                if entry.preset_id == preset_id
                and entry.email.casefold() == normalized_email
                and entry.user_id == user_id
            ),
            None,
        )

    def find_auth_target(
        self,
        *,
        preset_id: str,
        email: str,
        user_id: str,
    ) -> MemberAuthHandoffCatalogEntry | None:
        normalized_email = email.casefold()
        return next(
            (
                entry
                for entry in (*self.entries, *self.owner_entries)
                if entry.preset_id == preset_id
                and entry.email.casefold() == normalized_email
                and entry.user_id == user_id
            ),
            None,
        )

    def auth_entries_for_workspace(self, workspace_id: str) -> tuple[MemberAuthHandoffCatalogEntry, ...]:
        return tuple(
            entry
            for entry in (*self.entries, *self.owner_entries)
            if entry.workspace_id == workspace_id
        )

    def contains_member(
        self,
        *,
        workspace_id: str,
        email: str,
        user_id: str | None,
    ) -> bool:
        normalized_email = email.casefold()
        return any(
            entry.workspace_id == workspace_id
            and entry.email.casefold() == normalized_email
            and entry.user_id == user_id
            for entry in self.entries
        )

    def find_import_identity(
        self,
        *,
        workspace_account_id: str,
        email: str,
    ) -> MemberAuthHandoffCatalogEntry | None:
        normalized_email = email.strip().casefold()
        matches = tuple(
            entry
            for entry in self.entries
            if entry.workspace_account_id == workspace_account_id
            and entry.email.strip().casefold() == normalized_email
        )
        return matches[0] if len(matches) == 1 else None


class MemberAuthCatalogRegistrationError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class MemberAuthHandoffCatalogRegistry:
    def __init__(
        self,
        repository: MemberAuthCatalogOverlayRepository,
        packaged_catalog: MemberAuthHandoffCatalog,
    ) -> None:
        self._repository = repository
        self._packaged_catalog = packaged_catalog
        self._lock = RLock()

    def effective_catalog(self) -> MemberAuthHandoffCatalog:
        with self._lock:
            custom_entries = tuple(self._to_catalog_entry(record) for record in self._repository.load())
            return MemberAuthHandoffCatalog(
                entries=self._packaged_catalog.entries + custom_entries,
                owner_entries=self._packaged_catalog.owner_entries,
            )

    def register(
        self,
        request: CatalogMemberRegistrationRequest,
    ) -> CatalogMemberRegistrationResponse:
        with self._lock:
            workspace_entries = tuple(
                entry for entry in self._packaged_catalog.entries if entry.workspace_id == request.workspace_id
            )
            if not workspace_entries:
                raise MemberAuthCatalogRegistrationError(
                    "workspace_not_found",
                    "The selected member-switch workspace is not configured.",
                    status_code=404,
                )

            owner_email = workspace_entries[0].owner_email
            workspace_account_id = workspace_entries[0].workspace_account_id
            normalized_email = request.email.casefold()
            if normalized_email == owner_email.casefold():
                raise MemberAuthCatalogRegistrationError(
                    "owner_not_allowed",
                    "The workspace owner cannot be registered as a member candidate.",
                )

            records = list(self._repository.load())
            effective_entries = self._packaged_catalog.entries + tuple(
                self._to_catalog_entry(record) for record in records
            )
            exact = next(
                (
                    entry
                    for entry in effective_entries
                    if entry.workspace_id == request.workspace_id
                    and entry.preset_id == request.preset_id
                    and entry.email.casefold() == normalized_email
                    and entry.user_id == request.user_id
                ),
                None,
            )
            if exact is not None:
                return self._response("already_registered", request, exact.workspace_account_id)

            if any(entry.preset_id == request.preset_id for entry in effective_entries):
                raise MemberAuthCatalogRegistrationError(
                    "preset_id_conflict",
                    "The generated candidate preset ID is already bound to another identity.",
                )
            workspace_candidates = tuple(
                entry for entry in effective_entries if entry.workspace_id == request.workspace_id
            )
            if len(workspace_candidates) >= _MAX_MEMBERS_PER_WORKSPACE:
                raise MemberAuthCatalogRegistrationError(
                    "workspace_capacity_exceeded",
                    "The workspace candidate capacity has been reached.",
                )
            if any(entry.email.casefold() == normalized_email for entry in workspace_candidates):
                raise MemberAuthCatalogRegistrationError(
                    "email_conflict",
                    "The email is already registered in this workspace.",
                )
            if any(entry.user_id == request.user_id for entry in workspace_candidates):
                raise MemberAuthCatalogRegistrationError(
                    "user_id_conflict",
                    "The user ID is already registered in this workspace.",
                )

            records.append(
                CustomMemberAuthCatalogRecord(
                    workspace_id=request.workspace_id,
                    preset_id=request.preset_id,
                    display_name=request.display_name,
                    email=request.email,
                    user_id=request.user_id,
                    owner_email=owner_email,
                    workspace_account_id=workspace_account_id,
                )
            )
            self._repository.save(tuple(records))
            return self._response("created", request, workspace_account_id)

    @staticmethod
    def _to_catalog_entry(
        record: CustomMemberAuthCatalogRecord,
    ) -> MemberAuthHandoffCatalogEntry:
        return MemberAuthHandoffCatalogEntry(
            preset_id=record.preset_id,
            workspace_id=record.workspace_id,
            owner_email=record.owner_email,
            workspace_account_id=record.workspace_account_id,
            email=record.email,
            user_id=record.user_id,
        )

    @staticmethod
    def _response(
        code: str,
        request: CatalogMemberRegistrationRequest,
        workspace_account_id: str,
    ) -> CatalogMemberRegistrationResponse:
        return CatalogMemberRegistrationResponse(
            accepted=True,
            code=code,
            member=CatalogMemberIdentity(
                workspace_id=request.workspace_id,
                preset_id=request.preset_id,
                display_name=request.display_name,
                email=request.email,
                user_id=request.user_id,
                workspace_account_id=workspace_account_id,
            ),
        )


def _entry(
    preset_id: str,
    workspace_id: str,
    email: str,
    user_id: str,
) -> MemberAuthHandoffCatalogEntry:
    owner_email = {
        "cdp-1": "jaekwonhong14@gmail.com",
        "cdp-2": "thinklet03@gmail.com",
        "cdp-3": "thanks.for.confirming@gmail.com",
    }[workspace_id]
    workspace_account_id = {
        "cdp-1": "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        "cdp-2": "85d8ee33-bc27-4413-b3dc-24605885d5b0",
        "cdp-3": "5b9ab31e-fceb-4661-9655-1f479369c68f",
    }[workspace_id]
    return MemberAuthHandoffCatalogEntry(
        preset_id,
        workspace_id,
        owner_email,
        workspace_account_id,
        email,
        user_id,
    )


_WORKSPACE_1 = "cdp-1"
_WORKSPACE_2 = "cdp-2"
_WORKSPACE_3 = "cdp-3"

_WORKSPACE_LABEL_BY_ACCOUNT_ID = {
    "4865cea4-fb0b-41f3-917c-b226b2acdfb0": "workspace-1",
    "85d8ee33-bc27-4413-b3dc-24605885d5b0": "workspace-2",
    "5b9ab31e-fceb-4661-9655-1f479369c68f": "workspace-3",
}


def resolve_catalog_workspace_label(workspace_account_id: str) -> str | None:
    return _WORKSPACE_LABEL_BY_ACCOUNT_ID.get(workspace_account_id)

PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG = MemberAuthHandoffCatalog(
    entries=(
        _entry("cdp-1-allnz-jk", _WORKSPACE_1, "allnz.jk@gmail.com", "user-F35N1VBxC5M3BC4LQHhamB8a"),
        _entry("cdp-1-thinklet03", _WORKSPACE_1, "thinklet03@gmail.com", "user-9I446YqZTQ9z0Wq6zCzvJ0Sl"),
        _entry("cdp-1-thinklet09", _WORKSPACE_1, "thinklet09@gmail.com", "user-9c3ymeVJZPUGcGW9iqJdXhyK"),
        _entry(
            "cdp-1-thanks-for-confirming",
            _WORKSPACE_1,
            "thanks.for.confirming@gmail.com",
            "user-AlxoU0p7trJKi4FfVfEjXFnC",
        ),
        _entry("cdp-1-invoice-anse", _WORKSPACE_1, "invoice.anse@gmail.com", "user-zaX9Okb7Zo2jk68lJnJn7ps0"),
        _entry("cdp-2-allnz-jk", _WORKSPACE_2, "allnz.jk@gmail.com", "user-F35N1VBxC5M3BC4LQHhamB8a"),
        _entry(
            "cdp-2-jaekwonhong14",
            _WORKSPACE_2,
            "jaekwonhong14@gmail.com",
            "user-pQlg20Jguwdu0SCQgCFxvw6w",
        ),
        _entry("cdp-2-thinklet09", _WORKSPACE_2, "thinklet09@gmail.com", "user-9c3ymeVJZPUGcGW9iqJdXhyK"),
        _entry(
            "cdp-2-thanks-for-confirming",
            _WORKSPACE_2,
            "thanks.for.confirming@gmail.com",
            "user-AlxoU0p7trJKi4FfVfEjXFnC",
        ),
        _entry("cdp-2-invoice-anse", _WORKSPACE_2, "invoice.anse@gmail.com", "user-zaX9Okb7Zo2jk68lJnJn7ps0"),
        _entry("cdp-3-allnz-jk", _WORKSPACE_3, "allnz.jk@gmail.com", "user-F35N1VBxC5M3BC4LQHhamB8a"),
        _entry(
            "cdp-3-jaekwonhong14",
            _WORKSPACE_3,
            "jaekwonhong14@gmail.com",
            "user-pQlg20Jguwdu0SCQgCFxvw6w",
        ),
        _entry("cdp-3-thinklet03", _WORKSPACE_3, "thinklet03@gmail.com", "user-9I446YqZTQ9z0Wq6zCzvJ0Sl"),
        _entry("cdp-3-thinklet09", _WORKSPACE_3, "thinklet09@gmail.com", "user-9c3ymeVJZPUGcGW9iqJdXhyK"),
        _entry("cdp-3-invoice-anse", _WORKSPACE_3, "invoice.anse@gmail.com", "user-zaX9Okb7Zo2jk68lJnJn7ps0"),
    )
)
