__all__ = ["PDFProcessor", "calculate_md5", "setup_logger", "create_console"]


def __getattr__(name: str):
    if name == "PDFProcessor":
        from paperinsight.utils.pdf_utils import PDFProcessor
        return PDFProcessor
    if name == "calculate_md5":
        from paperinsight.utils.hash_utils import calculate_md5
        return calculate_md5
    if name == "setup_logger":
        from paperinsight.utils.logger import setup_logger
        return setup_logger
    if name == "create_console":
        from paperinsight.utils.terminal import create_console
        return create_console
    raise AttributeError(name)
