from django.conf.urls import url
from django.http import HttpResponse

from order.views import PurchaseOrderDetail
from order.models import PurchaseOrder
from plugin import InvenTreePlugin
from plugin.mixins import PanelMixin, SettingsMixin, UrlsMixin
import requests
import json

class SupplierCartPanel(PanelMixin, SettingsMixin, InvenTreePlugin, UrlsMixin):

    # Define data that is displayed on the panel
    Message=''
    Data=[]
    Total=0
    Proxies={}

    NAME = "SupplierCart"
    SLUG = "suppliercart"
    TITLE = "Create Mouser Cart"
    AUTHOR = "Michael"
    DESCRIPTION = "This plugin allows to transfer a PO into a mouser shopping cart."
    VERSION = "0.1"

    SETTINGS = {
        'SUPPLIERKEY': {
            'name': 'Supplier API key',
            'description': 'Place here your key for the suppliers API',
        },
        'CARTKEY': {
            'name': 'Supplier shopping cart key',
            'description': 'Place here your key for the shopping cart',
        },
        'PROXY_CON': {
            'name': 'Proxy CON',
            'description': 'Connection protocol to proxy server if needed e.g. https',
        },
        'PROXY_URL': {
            'name': 'Proxy URL',
            'description': 'URL to proxy server if needed e.g. http://user:password@ipaddress:port',
        },
        'LOCALE': {
            'name': 'Locale',
            'description': 'Here you can set locale string for decimal conversion',
            'default': 'de_DE.UTF-8',
        },

    }

# Create some help  
    def get_settings_content(self, request):
        return """
        <p>Setup:</p>
        <ol>
        <li>Create a key for the Mouser API</li>
        <li>RTFM</li>
        <li>Enable the plugin</li>
        <li>Put keys into settings</li>
        <li>Enjoy</li>
        """

# Create the panel that will display on the PurchaseOrder view,
    def get_custom_panels(self, view, request):
        panels = []

        if isinstance(view, PurchaseOrderDetail):
            panels.append({
                'title': 'Mouser Actions',
                'icon': 'fa-user',
                'content_template': 'supplier_panel/mouser.html', 
            })
        return panels

    def setup_urls(self):
        return [
            url(r'transfercart/(?P<pk>\d+)/', self.TransferCart, name='transfer-cart'),
        ]

#------------------------- Helper functions ------------------------------------
    def SendRequest(self, Cart, Path):
        headers = {'Content-type': 'application/json', 'Accept': 'application/json'}
        try:
            Response=requests.post(Path+'?apiKey='+self.get_setting('SUPPLIERKEY')+'&countryCode=DE',
                    verify=False,
                    proxies=self.Proxies,
                    data=json.dumps(Cart),
                    timeout=5,
                    headers=headers)
            Response.error_type = "OK"
        except (requests.ConnectTimeout, requests.HTTPError, requests.ReadTimeout, requests.Timeout, requests.ConnectionError) as error:
            Response=requests.models.Response()
            Response.error_type = "Connection Error"
            Response.status_code = 500
        return(Response)

#------------------------- UpdateSupplierCart ----------------------------------
# Sends the PO data to the supplier and gets back the result.

    def UpdateSupplierCart(self, Data):
        cart={
          "CartKey": self.get_setting('CARTKEY'),
          "CartItems":Data
        }
        Path= 'https://api.mouser.com/api/v001/cart'
        Response=self.SendRequest(cart,Path)
        return(Response)

#--------------------- CreateCartKey ---------------------------------------
# If there is no CartKey in the settings we just send an insert request with
# an empty CartKey string. The supplier creates a Cartkey in that case and sends
# it back. Surprisingly the part doses not show up in the newly created cart. 
# So there is no need to remove it. 

    def CreateCartKey(self):
        cart={
          "CartKey": '',
          "CartItems":[
             {
               "MouserPartNumber": '595-6PAIC3104IRHBRQ1',
               "Quantity": 1,
             }
          ]
        }
        Path='https://api.mouser.com/api/v001/cart/items/insert'
        Response=self.SendRequest(cart,Path)
        return(Response)

#------------------------ Interface functions start here --------------------
#---------------------------- TransferCart ---------------------------------------    
# This is called when the button is pressed. 

    def TransferCart(self,request,pk):
        if self.get_setting('PROXY_CON') != '':
            self.Proxies = {self.get_setting('PROXY_CON') : self.get_setting('PROXY_URL')}
        else:
            self.Proxies = {}
        if self.get_setting('CARTKEY') == '':
            Response=self.CreateCartKey()
            if Response.status_code != 200:
                self.Message=str(Response.status_code)+' '+Response.error_type
                return HttpResponse(f'Error')
            CartKey=Response.json()['CartKey']
            self.set_setting('CARTKEY',CartKey)
        CartItems=[]
        self.Data=[]
        Total=0
        Order=PurchaseOrder.objects.filter(id=pk).all()[0]
        if Order.supplier.name  != 'Mouser':
            self.Message='Supplier of this order is not Mouser'
            return HttpResponse(f'Error')
        for item in Order.lines.all():
            CartItems.append({'MouserPartNumber':item.part.SKU, 
                              'Quantity':int(item.quantity),
                              'CustomerPartNumber':item.part.part.IPN})
            if item.part.SKU =='N/A':
                self.Message='Part '+item.part.part.IPN+' is not available at Mouser. Please remove from PO'
                return HttpResponse(f'Error')
        Response=self.UpdateSupplierCart(CartItems)
        CartData=Response.json()
        if Response.status_code != 200:
            self.Message=str(Response.status_code)+' '+Response.error_type
            return HttpResponse(f'Error')
        if CartData['Errors'] != []:
            self.Message=str(Response.status_code)+' Cart Data Error'
            return HttpResponse(f'Error')
        Status={False:'Depleted',True:'OK'}
        for CartItem in CartData['CartItems']:
            self.Data.append({'PCS':CartItem['Quantity'],
                              'SKU':CartItem['MouserPartNumber'],
                              'IPN':CartItem['CartItemCustPartNumber'],
                              'status':Status[CartItem['Quantity'] <= CartItem['MouserATS']],
                              'price':CartItem['UnitPrice'],
                              'total':CartItem['ExtendedPrice'],
                              'available':CartItem['MouserATS'],
                              'currency':CartData['CurrencyCode'],
                              })
        self.Total=CartData['MerchandiseTotal']
        self.Message=str(Response.status_code)+' '+Response.error_type
        return HttpResponse(f'OK')
