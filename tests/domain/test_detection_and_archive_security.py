from pig.domain.archive_security import evaluate_archive_entry_path
from pig.domain.detection import detect_node_format
from pig.domain.enums import ErrorCode, NodeFormat, NodeKind


def test_archive_path_policy_accepts_nested_relative_member() -> None:
    decision = evaluate_archive_entry_path(
        "邮件资料/供应商报价.pdf", is_symbolic_link=False
    )
    assert decision.allowed
    assert decision.safe_parts == ("邮件资料", "供应商报价.pdf")


def test_archive_path_policy_rejects_platform_independent_unsafe_forms() -> None:
    cases = {
        "a/../outside.txt": ErrorCode.PATH_TRAVERSAL_BLOCKED,
        "/absolute.txt": ErrorCode.ABSOLUTE_PATH_BLOCKED,
        "C:\\absolute.txt": ErrorCode.ABSOLUTE_PATH_BLOCKED,
        "\\\\?\\C:\\device.txt": ErrorCode.DEVICE_PATH_BLOCKED,
        "name\x00.txt": ErrorCode.INVALID_FILENAME,
    }
    for name, code in cases.items():
        decision = evaluate_archive_entry_path(name, is_symbolic_link=False)
        assert not decision.allowed
        assert decision.error_code == code


def test_archive_path_policy_always_rejects_symbolic_link_entry() -> None:
    decision = evaluate_archive_entry_path("safe-name", is_symbolic_link=True)
    assert not decision.allowed
    assert decision.error_code == ErrorCode.SYMLINK_BLOCKED


def test_detector_uses_signature_for_renamed_zip() -> None:
    result = detect_node_format("evidence.bin", b"PK\x03\x04data")
    assert result.kind == NodeKind.CONTAINER
    assert result.format == NodeFormat.ZIP
    assert result.method == "zip_signature"


def test_detector_uses_signature_for_renamed_seven_z_and_rar() -> None:
    seven_z = detect_node_format("archive.bin", b"7z\xbc\xaf\x27\x1cdata")
    rar = detect_node_format("archive.bin", b"Rar!\x1a\x07\x01\x00")

    assert seven_z.kind == NodeKind.CONTAINER
    assert seven_z.format == NodeFormat.SEVEN_Z
    assert seven_z.method == "seven_z_signature"
    assert rar.kind == NodeKind.CONTAINER
    assert rar.format == NodeFormat.RAR
    assert rar.method == "rar_signature"


def test_detector_keeps_office_open_xml_terminal() -> None:
    result = detect_node_format("report.xlsx", b"PK\x03\x04data")
    assert result.kind == NodeKind.FILE
    assert result.format == NodeFormat.XLSX


def test_detector_unknown_file_is_a_valid_terminal_file() -> None:
    result = detect_node_format("evidence.custom", b"data")
    assert result.kind == NodeKind.FILE
    assert result.format == NodeFormat.UNKNOWN


def test_detector_folder_is_deterministic() -> None:
    result = detect_node_format("folder.zip", b"PK\x03\x04", is_directory=True)
    assert result.kind == NodeKind.CONTAINER
    assert result.format == NodeFormat.FOLDER
