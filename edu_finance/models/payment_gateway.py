# -*- coding: utf-8 -*-
"""Payment Gateway — dispatcher model and abstract adapter interface.

This implements the **Gateway Adapter Pattern** from the MASTER_PLAN. The
architecture decouples the education finance engine (cc.finance) from
specific payment providers (Payme, Click, Uzum, etc.).

Two models:
  1. ``payment.gateway`` — a concrete stored model representing one configured
     gateway instance (e.g. "Payme Production", "Click Sandbox"). It holds
     provider credentials and dispatches calls to the right adapter.
  2. ``payment.gateway.adapter`` — an AbstractModel (no database table) that
     defines the interface contract. Concrete providers inherit it and
     implement the three abstract methods.

Adding a new provider:
  1. Create a new module (e.g. ``payment_payme``).
  2. Define a model inheriting ``payment.gateway.adapter``:
       class PaymeAdapter(models.AbstractModel):
           _inherit = 'payment.gateway.adapter'
  3. Add a new selection value to ``payment.gateway.provider``.
  4. Implement ``_process_payment``, ``_verify_payment``, ``_cancel_payment``.
  5. Done. cc.finance and the ledger remain untouched.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class PaymentGateway(models.Model):
    """A configured payment gateway instance.

    Each record represents one active gateway configuration (credentials,
    environment, provider). The ``provider`` field determines which adapter
    implementation is used at dispatch time.
    """
    _name = 'payment.gateway'
    _description = 'Payment Gateway Configuration'
    _order = 'sequence, name'
    _inherit = ['mail.thread']

    name = fields.Char(
        string='Gateway Name',
        required=True,
        tracking=True,
        help="Human-readable label, e.g. 'Payme Production' or 'Click Test'.",
    )

    provider = fields.Selection(
        selection='_get_provider_selection',
        string='Provider',
        required=True,
        tracking=True,
        help="The payment provider this gateway connects to. Each provider "
             "has a corresponding adapter implementation.",
    )

    environment = fields.Selection(
        selection=[
            ('test', 'Test / Sandbox'),
            ('production', 'Production'),
        ],
        string='Environment',
        required=True,
        default='test',
        tracking=True,
    )

    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )

    # ------------------------------------------------------------------
    # CREDENTIALS (stored encrypted in production via Odoo's field encryption
    # or an external vault; here we define the schema)
    # ------------------------------------------------------------------
    merchant_id = fields.Char(
        string='Merchant ID',
        help="Provider-specific merchant identifier.",
    )
    api_key = fields.Char(
        string='API Key / Secret',
        help="Provider API key or secret token. Store securely.",
    )
    api_endpoint = fields.Char(
        string='API Endpoint URL',
        help="Base URL of the provider's API (auto-set per environment if empty).",
    )
    webhook_secret = fields.Char(
        string='Webhook Secret',
        help="Secret used to verify incoming webhook signatures.",
    )
    extra_config = fields.Text(
        string='Extra Configuration (JSON)',
        help="Provider-specific additional configuration as a JSON object.",
    )

    # ------------------------------------------------------------------
    # STATISTICS
    # ------------------------------------------------------------------
    transaction_count = fields.Integer(
        string='Transactions',
        compute='_compute_transaction_count',
        store=False,
    )

    @api.depends()
    def _compute_transaction_count(self):
        Finance = self.env['cc.finance']
        for gw in self:
            gw.transaction_count = Finance.search_count([
                ('gateway_id', '=', gw.id),
            ])

    # ------------------------------------------------------------------
    # PROVIDER SELECTION (extensible by inheriting modules)
    # ------------------------------------------------------------------
    @api.model
    def _get_provider_selection(self):
        """Return the list of available providers.

        Each concrete gateway module extends this list by overriding and
        calling super(). The base provides a placeholder so the model is
        installable without any provider.

        Override example in payment_payme:
            @api.model
            def _get_provider_selection(self):
                res = super()._get_provider_selection()
                res.append(('payme', 'Payme'))
                return res
        """
        return [
            ('none', '(No Provider — Manual Only)'),
        ]

    # ------------------------------------------------------------------
    # DISPATCH TO ADAPTER
    # ------------------------------------------------------------------
    def _get_adapter(self):
        """Resolve and return the adapter AbstractModel for this gateway's provider.

        Convention: the adapter model is named ``payment.gateway.<provider>``.
        If not found, falls back to the base ``payment.gateway.adapter``.
        """
        self.ensure_one()
        adapter_name = 'payment.gateway.%s' % self.provider
        if adapter_name in self.env:
            return self.env[adapter_name]
        # Fall back to the base abstract adapter (which raises NotImplemented)
        return self.env['payment.gateway.adapter']

    def _dispatch_process_payment(self, data):
        """Dispatch a payment processing request to the provider adapter.

        Args:
            data (dict): Standard payment data dict with keys:
                - finance_id: int
                - amount: float
                - currency: str (e.g. 'UZS')
                - partner_id: int or False
                - reference: str
                - description: str

        Returns:
            dict with at least: {'reference': str, 'state': str}
        """
        self.ensure_one()
        self._check_gateway_ready()
        adapter = self._get_adapter()
        return adapter._process_payment(self, data)

    def _dispatch_verify_payment(self, data):
        """Dispatch a payment verification request to the provider adapter.

        Args:
            data (dict): Verification data with keys:
                - finance_id: int
                - reference: str (the gateway transaction id)

        Returns:
            dict with at least: {'state': str} where state is one of
            'pending', 'verified', 'failed'. May include 'error' on failure.
        """
        self.ensure_one()
        self._check_gateway_ready()
        adapter = self._get_adapter()
        return adapter._verify_payment(self, data)

    def _dispatch_cancel_payment(self, data):
        """Dispatch a payment cancellation request to the provider adapter.

        Args:
            data (dict): Cancellation data with keys:
                - finance_id: int
                - reference: str

        Returns:
            dict with at least: {'state': str, 'cancelled': bool}
        """
        self.ensure_one()
        self._check_gateway_ready()
        adapter = self._get_adapter()
        return adapter._cancel_payment(self, data)

    def _check_gateway_ready(self):
        """Validate that the gateway is properly configured before dispatch."""
        self.ensure_one()
        if not self.active:
            raise UserError(_(
                "Payment gateway '%(name)s' is disabled.",
                name=self.name,
            ))
        if self.provider == 'none':
            raise UserError(_(
                "Payment gateway '%(name)s' has no provider configured. "
                "Please select a provider (Payme, Click, Uzum, etc.).",
                name=self.name,
            ))

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------
    def action_view_transactions(self):
        """Open finance records processed through this gateway."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Gateway Transactions'),
            'res_model': 'cc.finance',
            'view_mode': 'list,form',
            'domain': [('gateway_id', '=', self.id)],
            'context': {'default_gateway_id': self.id},
        }

    def action_test_connection(self):
        """Test connectivity to the provider (adapter must implement)."""
        self.ensure_one()
        adapter = self._get_adapter()
        if hasattr(adapter, '_test_connection'):
            result = adapter._test_connection(self)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': result.get('message', _('Connection successful!')),
                    'type': result.get('type', 'success'),
                    'sticky': False,
                },
            }
        raise UserError(_(
            "The adapter for provider '%(provider)s' does not implement "
            "connection testing.",
            provider=self.provider,
        ))


class PaymentGatewayAdapter(models.AbstractModel):
    """Abstract adapter interface for payment gateway providers.

    This defines the contract that every concrete provider must implement.
    It is an AbstractModel (no database table) — concrete providers inherit
    this and provide real implementations.

    Naming convention: ``payment.gateway.<provider_key>``
    Example: ``payment.gateway.payme``, ``payment.gateway.click``

    Each method receives the ``gateway`` record (with credentials/config)
    and a standardized ``data`` dict. The adapter translates between our
    internal format and the provider's API.

    DO NOT put any ledger/accounting logic here. The adapter only handles
    the external communication. Ledger posting is always done by cc.finance.
    """
    _name = 'payment.gateway.adapter'
    _description = 'Payment Gateway Adapter (Abstract Interface)'

    def _process_payment(self, gateway, data):
        """Initiate a payment with the external provider.

        This is called when cc.finance.action_process_via_gateway() is invoked.
        The adapter should:
          1. Build the provider-specific API request.
          2. Send it to the provider's endpoint.
          3. Return the initial response.

        Args:
            gateway (payment.gateway): The gateway record with credentials.
            data (dict): Standardized payment data:
                - finance_id (int): ID of the cc.finance record.
                - amount (float): Payment amount.
                - currency (str): Currency code (e.g. 'UZS').
                - partner_id (int|False): Student/contact res.partner ID.
                - reference (str): Our internal reference (cc.finance.name).
                - description (str): Human-readable description.

        Returns:
            dict: Must contain at minimum:
                - reference (str): The provider's transaction ID/reference.
                - state (str): One of 'pending', 'verified', 'failed'.
                May also contain:
                - redirect_url (str): URL to redirect user to (for hosted checkout).
                - raw_response (dict): Full provider response for debugging.

        Raises:
            UserError: If the provider returns an unrecoverable error.
            NotImplementedError: If this base class is called directly.
        """
        raise NotImplementedError(_(
            "Payment processing is not implemented for provider '%(provider)s'. "
            "Please install the corresponding gateway module.",
            provider=gateway.provider,
        ))

    def _verify_payment(self, gateway, data):
        """Verify the status of an existing payment with the provider.

        Called by webhook controllers or manual verification. The adapter
        should query the provider's API for the current transaction status.

        Args:
            gateway (payment.gateway): The gateway record with credentials.
            data (dict): Verification data:
                - finance_id (int): ID of the cc.finance record.
                - reference (str): The provider's transaction ID.

        Returns:
            dict: Must contain at minimum:
                - state (str): One of 'pending', 'verified', 'failed'.
                May also contain:
                - error (str): Error message if failed.
                - paid_amount (float): Actual amount paid (for partial payments).
                - raw_response (dict): Full provider response for debugging.

        Raises:
            UserError: If verification request fails.
            NotImplementedError: If this base class is called directly.
        """
        raise NotImplementedError(_(
            "Payment verification is not implemented for provider '%(provider)s'. "
            "Please install the corresponding gateway module.",
            provider=gateway.provider,
        ))

    def _cancel_payment(self, gateway, data):
        """Request cancellation of a pending payment with the provider.

        Not all providers support cancellation. If unsupported, the adapter
        should return {'cancelled': False, 'state': 'pending'}.

        Args:
            gateway (payment.gateway): The gateway record with credentials.
            data (dict): Cancellation data:
                - finance_id (int): ID of the cc.finance record.
                - reference (str): The provider's transaction ID.

        Returns:
            dict: Must contain:
                - cancelled (bool): Whether cancellation was successful.
                - state (str): New transaction state.
                May also contain:
                - error (str): Reason if cancellation failed.

        Raises:
            NotImplementedError: If this base class is called directly.
        """
        raise NotImplementedError(_(
            "Payment cancellation is not implemented for provider '%(provider)s'. "
            "Please install the corresponding gateway module.",
            provider=gateway.provider,
        ))

    def _test_connection(self, gateway):
        """Test connectivity to the provider's API (optional).

        Args:
            gateway (payment.gateway): The gateway record with credentials.

        Returns:
            dict: {'message': str, 'type': 'success'|'warning'|'danger'}
        """
        return {
            'message': _(
                "Connection test not implemented for provider '%(provider)s'.",
                provider=gateway.provider,
            ),
            'type': 'warning',
        }
