"""
Authentication utilities for Azure AI Foundry
"""

from typing import Any
from azure.core.credentials import AccessToken
from azure.core.credentials_async import AsyncTokenCredential


class APIKeyTokenCredential(AsyncTokenCredential):
    """
    Token credential that wraps an API key for services that expect TokenCredential
    but use API key authentication.
    """

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def get_token(
        self, *scopes: str, claims: str | None = None, tenant_id: str | None = None, **kwargs: Any
    ) -> AccessToken:
        """
        Return an AccessToken with the API key as the token value.

        Note: This is a workaround for services that expect TokenCredential
        but actually use API key authentication in the HTTP headers.
        """
        # Return API key with a far-future expiration
        return AccessToken(token=self._api_key, expires_on=9999999999)

    async def close(self) -> None:
        """No resources to clean up"""
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
