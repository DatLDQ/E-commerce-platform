"""File storage that keeps uploads in the database.

Free web hosts such as Render give each deploy a fresh disk, so files written to MEDIA_ROOT
(product photos and banners uploaded through the admin) disappear on the next deploy or restart.
Storing them as rows in PostgreSQL keeps them for as long as the database lives.
"""
import mimetypes
from urllib.parse import urljoin

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible
from django.utils.encoding import filepath_to_uri


@deconstructible
class DatabaseStorage(Storage):
    def _model(self):
        from .models import StoredFile

        return StoredFile

    def _open(self, name, mode="rb"):
        row = self._model().objects.filter(name=name).only("content").first()
        if row is None:
            raise FileNotFoundError(name)
        return ContentFile(bytes(row.content), name=name)

    def _save(self, name, content):
        if hasattr(content, "seek"):
            content.seek(0)
        data = content.read()
        if isinstance(data, str):
            data = data.encode()
        self._model().objects.update_or_create(name=name, defaults={"content": data, "size": len(data)})
        return name

    def exists(self, name):
        return self._model().objects.filter(name=name).exists()

    def delete(self, name):
        self._model().objects.filter(name=name).delete()

    def size(self, name):
        row = self._model().objects.filter(name=name).only("size").first()
        if row is None:
            raise FileNotFoundError(name)
        return row.size

    def url(self, name):
        return urljoin(settings.MEDIA_URL, filepath_to_uri(name))

    def listdir(self, path):
        prefix = path.rstrip("/") + "/" if path else ""
        dirs, files = set(), []
        for n in self._model().objects.filter(name__startswith=prefix).values_list("name", flat=True):
            head, _, tail = n[len(prefix):].partition("/")
            (dirs.add(head) if tail else files.append(head))
        return sorted(dirs), files


def content_type(name):
    return mimetypes.guess_type(name)[0] or "application/octet-stream"
