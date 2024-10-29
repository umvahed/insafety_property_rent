import time 
import locale
from odoo import _
from odoo import models, fields, api
from odoo.exceptions import ValidationError
import json

class Property(models.Model):
    _name = 'insafety.property.building'
    _inherit = "mail.thread"
    _description = 'Real Estate Property Building'
    _check_company_auto = True


    name = fields.Char(string="Name", required=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, readonly=True,
        default=lambda self: self.env.company)
    description = fields.Text(string="Description", tracking=True)
    account_receivable_id = fields.Many2one('account.account', string="Default Account Receivable", 
                                            domain=[('deprecated', '=', False)], check_company=True, required=True, tracking=True)
    tax_ids = fields.Many2many('account.tax', string='Taxes', domain=[('active', '=', True)], tracking=True)
    invoice_payment_term_id = fields.Many2one('account.payment.term', string="Rent Payment Term", required=True, tracking=True)
    qr_code_method = fields.Selection(
        string="Rent QR-code", copy=False,
        selection=lambda self: self.env['res.partner.bank'].get_available_qr_methods_in_sequence(),
        help="Type of QR-code to be generated for the payment of this invoice, "
             "when printing it. If left blank, the first available and usable method "
             "will be used.",
    )
    account_payable_id = fields.Many2one('account.account', tracking=True,
                                         string="Account Payable", domain=[('deprecated', '=', False),('account_type','=','expense')], check_company=True)
    administrative_expenses = fields.Float(string="Administrative Expenses Percentage", tracking=True)

    total_area = fields.Integer(string="Total Area (sqm)", compute="_compute_total_area")
    total_volume = fields.Float(string="Total Volume", compute="_compute_total_area")
    total_rooms =fields.Float(string="Total Rooms", compute="_compute_total_area")
    total_cost_factor_custom = fields.Float(string="Total Cost Factor Custom", compute="_compute_total_area")

    property_count = fields.Integer(string="Number of Properties", compute="_compute_total_area")
    property_ids = fields.One2many('insafety.property','building_id', string="Properties")
    distribute_by = fields.Selection([("rooms", "Rooms"),("area", "Area"),("volume", "Volume"),("custom", "Custom"), ("equal", "Equal")], string="Distributed By", default="rooms", required=True)
    billing_period_from = fields.Date(string="Billing Period From", required=True)
    billing_period_to = fields.Date(string="Billing Period To", required=True)
    document = fields.Binary(string="Document", attachment=True )
    document_name = fields.Char(string="File Name")
    notes = fields.Html(string="Notes")

    account_expense_ids = fields.One2many('account.account','building_id', string="Expense", readonly=True, tracking=True)
    account_ids = fields.One2many('account.account','building_id', string="Accounts", tracking=True)
    
    total_expense = fields.Float(string="Total Expense", compute="_compute_total_expense")
    total_income = fields.Float(string="Total Income", compute="_compute_total_income")
    total_vacant_cost = fields.Float(string="Total Vacant Costs", compute="_compute_total")
    total_administrative_expenses = fields.Float(string="Total Administrative Expenses", compute="_compute_total")
    rent_contract_ids = fields.One2many("insafety.property.rent.contract", string="Contracts", compute="_compute_contracts")
    cost_billing_receivable_id = fields.Many2one('account.account', string="Cost Account Receivable", 
                                                 domain=[('deprecated', '=', False)], check_company=True, required=True, tracking=True)
    cost_billing_tax_ids = fields.Many2many('account.tax', string='Taxes Cost Billing', domain=[('active', '=', True)],relation="insafety_cost_billing_tax_ids")
    cost_billing_payment_term_id = fields.Many2one('account.payment.term', string="Cost Billing Payment Term", required=True, tracking=True)
    cost_billing_qr_code_method = fields.Selection(
        string="Payment QR-code", copy=False,
        selection=lambda self: self.env['res.partner.bank'].get_available_qr_methods_in_sequence(),
        help="Type of QR-code to be generated for the payment of this invoice, "
             "when printing it. If left blank, the first available and usable method "
             "will be used.",
    )

    cost_billing_administrative_fees_id = fields.Many2one('account.account', string="Administrative Fees", tracking=True,
                                                 domain=[('deprecated', '=', False)], check_company=True, required=True)
    cost_billing_administrative_tax_ids = fields.Many2many('account.tax', string='Administrative Fees Taxes', check_company=True, tracking=True,
                                                           domain=[('active', '=', True)], relation="insafety_cost_billing_administrative_tax_ids")

    cost_billing_direct_post = fields.Boolean(string="Direct Post", default=True)

    analytic_account_ids = fields.Many2many('account.analytic.account', string='Analytic Accounts', tracking=True)
    
  
    @api.depends('property_ids.rent_contract_ids','distribute_by')
    def _compute_contracts(self):
        for rec in self:    
         rec.rent_contract_ids = rec.property_ids.rent_contract_ids

    def _compute_total(self):
        for rec in self:
            next_cost_billing = 0
            for con in rec.rent_contract_ids:
                next_cost_billing += con.next_cost_billing
            rec.total_vacant_cost = rec.total_expense - next_cost_billing
            rec.total_administrative_expenses = next_cost_billing * rec.administrative_expenses / 100
    
    def _compute_total_expense(self):
        for rec in self:
            total = 0
            for acc in rec.account_expense_ids:
                total += acc.current_balance
            rec.total_expense = total

    def _compute_total_income(self):
        for rec in self:
            total = 0
            # for acc in rec.account_income_ids:
            #     total += acc.current_balance
            for acc in rec.rent_contract_ids.account_receivable_id:
                total += acc.current_balance
            rec.total_income = total
    

    def _compute_total_area(self):
        for rec in self:
            property_count = 0
            total_area = 0
            total_volume = 0
            total_rooms = 0
            total_cost_factor_custom = 0
            for property in rec.property_ids: 
                total_area += property.total_area
                total_volume += property.volume
                total_rooms += property.total_rooms
                property_count += 1
                total_cost_factor_custom += property.cost_factor_custom
            rec.total_area = total_area
            rec.property_count = property_count
            rec.total_volume = total_volume
            rec.total_rooms = total_rooms
            rec.total_cost_factor_custom = total_cost_factor_custom

    def create_invoice(self):
        self = self.with_company(self.company_id)
        building = self
        contracts = self.rent_contract_ids

        analyticAccounts = {}
        for a in building.analytic_account_ids:
            analyticAccounts[str(a.id)] = 100
        


        for contract in contracts:
            if contract.cost_billing_total != 0:
                move_type = 'out_invoice'
                cost_billing_total = contract.cost_billing_total
                if contract.cost_billing_total < 0:
                    move_type = 'in_invoice'
                    cost_billing_total =  0 - contract.cost_billing_total
                locale.setlocale(locale.LC_ALL, contract.tenant_id.lang + '.UTF-8')
                total_expense = building.total_expense
                fraction_expense = total_expense / 365 * contract.rent_days / contract.distribution_base * contract.distribution_key
                fraction_text = f"{_('Distribution')}: {building.distribute_by} {contract.distribution_base}/{contract.distribution_key} "
                if contract.rent_days != 365:
                        fraction_text += f"365/{contract.rent_days}"
                administrative_expenses = fraction_expense  * building.administrative_expenses / 100
                invoice = self.env['account.move'].create([
                            {
                                'move_type': move_type, 
                                'partner_id': contract.tenant_id.id,
                                'invoice_date': time.strftime('%Y-%m-01'),
                                'invoice_payment_term_id': building.cost_billing_payment_term_id.id,
                                'qr_code_method': building.cost_billing_qr_code_method,
                                'invoice_line_ids': [
                                    (0, 0, {'price_unit': cost_billing_total - administrative_expenses, 
                                                            'account_id': building.cost_billing_receivable_id.id, 
                                                            'tax_ids': building.cost_billing_tax_ids,
                                                            'name': _('Balance'),
                                                            'analytic_distribution': analyticAccounts}),
                                                      (0, 0, {'price_unit': administrative_expenses, 
                                                            'account_id': building.cost_billing_administrative_fees_id.id, 
                                                            'tax_ids': building.cost_billing_administrative_tax_ids,
                                                            'name': _('Administrative Fees'),
                                                            'analytic_distribution': analyticAccounts})           
                                                    ],
                            },
                        ])      
                text = f'''
                    <p style="page-break-before:always;"> </p>
                    <h5>{_('Aditional Cost Billing')}, {building.billing_period_from.strftime("%x")} - {building.billing_period_to.strftime("%x")}</h5>
                    <h5>{building.name}, {building.description}, {contract.property_id.name}, {contract.property_id.description} </h5>     
                    <table>
                    <tbody>
                '''
                cur = self.env.company.currency_id.display_name

                total_expense = building.total_expense
                fraction_expense = total_expense / 365 * contract.rent_days / contract.distribution_base * contract.distribution_key
                fraction_text = f"{_('share calc')}: {building.distribute_by} {contract.distribution_base}/{contract.distribution_key} "
                if contract.rent_days != 365:
                        fraction_text += f"365/{contract.rent_days}"
                administrative_expenses = fraction_expense  * building.administrative_expenses / 100

                if building.cost_billing_direct_post:
                    invoice.action_post()

                for expense in building.account_expense_ids:
                    text += f'''
                            <tr>
                                <td> {expense.name}&nbsp;</td>
                                <td>{expense.currency_id.display_name}&nbsp;</td>
                                <td style="text-align:right">{format(expense.current_balance, ".2f")}</td>
                            </tr>
                    '''        
                text += f'''
                </tbody>
                <tfoot>
                    <tr>
                        <td>Total</td>
                        <td>{cur}</td>
                        <td style="text-align:right">{format(total_expense, ".2f")}</td>
                    </tr>
                    <tr>
                        <td>{_('Your share')}*</td>
                        <td>{cur}</td>
                        <td style="text-align:right">{format(fraction_expense, ".2f")}</td>
                    </tr>
                    <tr>
                    <tr>
                        <td>{_('paid')}</td>
                        <td>{cur}</td>
                        <td style="text-align:right"> - {format(contract.monthly_extra_costs_paid_calc, ".2f")}</td>
                    </tr>
                    <tr>
                        <td>{_('Balance')}</td>
                        <td>{cur}</td>
                        <td style="text-align:right">{format(fraction_expense - contract.monthly_extra_costs_paid_calc, ".2f")}</td>
                    </tr>              
                </tfoot>
                </table>
                <p><br></p>
                <table>
                <tr>
                    <td>+ {_('Administrative Fees')}&nbsp;</td>
                    <td>{cur}&nbsp;</td>
                    <td style="text-align:right">{format(administrative_expenses, ".2f")}</td>
                </tr>
                </table>
                <div>*{fraction_text}</div>
                '''
                invoice.narration = text
    
    def calculate(self):
        pass

    def create_demo_invoice(self):
        ref = self.env.ref
        for building in self:
            acc1 = self.env['account.account'].search([('code', '=', "650004")])
            acc2 = self.env['account.account'].search([('code', '=', "650005")])
            acc3 = self.env['account.account'].search([('code', '=', "650006")])
            
            invoice1 = self.env['account.move'].create([
            {
                'move_type': 'in_invoice',
                'partner_id': ref('base.res_partner_12').id,
                'invoice_user_id': ref('base.user_demo').id,
                'invoice_payment_term_id': ref('account.account_payment_term_end_following_month').id,
                'invoice_date': time.strftime('%Y-%m-01'),
                'invoice_line_ids': [
                    (0, 0, {'price_unit': 4000, 
                                            'account_id': acc1.id, 
                                            'tax_ids': building.cost_billing_tax_ids,
                                            'name': _('Salary Care Taker')}),
                    
                                    ],
            },
            ])
            invoice1.action_post()
            invoice2 = self.env['account.move'].create([
            {
                'move_type': 'in_invoice',
                'partner_id': ref('base.res_partner_12').id,
                'invoice_user_id': ref('base.user_demo').id,
                'invoice_payment_term_id': ref('account.account_payment_term_end_following_month').id,
                'invoice_date': time.strftime('%Y-%m-01'),
                'invoice_line_ids': [
                    (0, 0, {'price_unit': 2500, 
                                            'account_id': acc2.id, 
                                            'tax_ids': building.cost_billing_tax_ids,
                                            'name': _('Yearly Engergy')}),
                    
                                    ],
            },
            ])
            invoice2.action_post() 
            invoice3 = self.env['account.move'].create([
            {
                'move_type': 'in_invoice',
                'partner_id': ref('base.res_partner_12').id,
                'invoice_user_id': ref('base.user_demo').id,
                'invoice_payment_term_id': ref('account.account_payment_term_end_following_month').id,
                'invoice_date': time.strftime('%Y-%m-01'),
                'invoice_line_ids': [
                    (0, 0, {'price_unit': 1500, 
                                            'account_id': acc3.id, 
                                            'tax_ids': building.cost_billing_tax_ids,
                                            'name': _('Yearly Water')}),
                    
                                    ],
            },
            ])
            print(invoice3) 
            invoice3.action_post()  

    def open_cron(self):
        rent_cron = self.env["ir.cron"].with_context(active_test=False).search(
            [("model_name", "=", "insafety.property.rent.contract")], limit=1)

        if rent_cron:
            return {
                'name': "Rent Cron Job",
                "view_type": "form",
                "res_model": "ir.cron",
                "res_id": rent_cron.id, 
                'view_id': False,
                'view_mode': "form",
                'type': "ir.actions.act_window"
            }




        
    