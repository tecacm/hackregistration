import os

import filetype
from django.core.exceptions import ValidationError


def validate_file_extension(valid_extensions, type_check=True):
    def wrapper(value):
        (_, ext) = os.path.splitext(value.name)
        if valid_extensions and ext.lower() not in valid_extensions:
            raise ValidationError('Unsupported file extension.')
        if type_check and valid_extensions:
            # Read a small header from the file to detect type, then reset pointer
            # Support only the provided extensions
            try:
                head = value.file.read(261)  # enough for PDF and most types
            finally:
                try:
                    value.file.seek(0)
                except Exception:
                    pass
            matches = [f_t for f_t in filetype.TYPES if ('.' + f_t.extension) in valid_extensions]
            if filetype.match(head, matches) is None:
                raise ValidationError('Unsupported file type.')
    return wrapper


def validate_file_size(max_mb: int):
    max_bytes = max_mb * 1024 * 1024

    def wrapper(value):
        size = getattr(value, 'size', None)
        if size is None:
            # Fallback: try reading content length without consuming stream
            try:
                pos = value.file.tell()
                value.file.seek(0, os.SEEK_END)
                size = value.file.tell()
                value.file.seek(pos)
            except Exception:
                size = max_bytes  # force failure if unknown
        if size > max_bytes:
            raise ValidationError(f'File too large. Max allowed size is {max_mb} MB.')

    return wrapper
