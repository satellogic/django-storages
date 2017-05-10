import mimetypes
import os.path
import time
from datetime import datetime, timedelta
from time import mktime

from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible
from azure.storage import AccessPolicy, SharedAccessPolicy

from storages.utils import setting

try:
    import azure  # noqa
except ImportError:
    raise ImproperlyConfigured(
        "Could not load Azure bindings. "
        "See https://github.com/WindowsAzure/azure-sdk-for-python")

try:
    # azure-storage 0.20.0
    from azure.storage.blob.blobservice import BlobService
    from azure.common import AzureMissingResourceHttpError
except ImportError:
    from azure.storage import BlobService
    from azure import WindowsAzureMissingResourceError as AzureMissingResourceHttpError


def clean_name(name):
    return os.path.normpath(name).replace("\\", "/")


@deconstructible
class AzureStorage(Storage):
    account_name = setting("AZURE_ACCOUNT_NAME")
    account_key = setting("AZURE_ACCOUNT_KEY")
    azure_container = setting("AZURE_CONTAINER")
    azure_ssl = setting("AZURE_SSL")

    def __init__(self, *args, **kwargs):
        super(AzureStorage, self).__init__(*args, **kwargs)
        self._connection = None

    @property
    def connection(self):
        if self._connection is None:
            self._connection = BlobService(
                self.account_name, self.account_key)
        return self._connection

    @property
    def azure_protocol(self):
        if self.azure_ssl:
            return 'https'
        return 'http' if self.azure_ssl is not None else None

    def __get_blob_properties(self, name):
        try:
            return self.connection.get_blob_properties(
                self.azure_container,
                name
            )
        except AzureMissingResourceHttpError:
            return None

    def _open(self, name, mode="rb"):
        contents = self.connection.get_blob(self.azure_container, name)
        return ContentFile(contents)

    def exists(self, name):
        return self.__get_blob_properties(name) is not None

    def delete(self, name):
        try:
            self.connection.delete_blob(self.azure_container, name)
        except AzureMissingResourceHttpError:
            pass

    def size(self, name):
        properties = self.connection.get_blob_properties(
            self.azure_container, name)
        return properties["content-length"]

    def _save(self, name, content):
        if hasattr(content.file, 'content_type'):
            content_type = content.file.content_type
        else:
            content_type = mimetypes.guess_type(name)[0]

        if hasattr(content, 'chunks'):
            content_data = b''.join(chunk for chunk in content.chunks())
        else:
            content_data = content.read()

        self.connection.put_blob(self.azure_container, name,
                                 content_data, "BlockBlob",
                                 x_ms_blob_content_type=content_type)
        return name

    def url(self, name, expire=None, mode='r'):
        if hasattr(self.connection, 'make_blob_url'):
            sas_token = None

            if expire:
                today = datetime.utcnow()
                today_plus_delta = today + timedelta(seconds=expire)
                today_plus_delta = today_plus_delta.replace(microsecond=0).isoformat() + 'Z'
                sas_token = self.connection.generate_shared_access_signature(self.azure_container, name,
                                                                            SharedAccessPolicy(
                                                                                AccessPolicy(mode, today_plus_delta,
                                                                                             None), None))
            return self.connection.make_blob_url(
                container_name=self.azure_container,
                blob_name=name,
                protocol=self.azure_protocol,
                sas_token=sas_token
            )
        else:
            return "{}{}/{}".format(setting('MEDIA_URL'), self.azure_container, name)

    def modified_time(self, name):
        try:
            modified = self.__get_blob_properties(name)['last-modified']
        except (TypeError, KeyError):
            return super(AzureStorage, self).modified_time(name)

        modified = time.strptime(modified, '%a, %d %b %Y %H:%M:%S %Z')
        modified = datetime.fromtimestamp(mktime(modified))

        return modified
