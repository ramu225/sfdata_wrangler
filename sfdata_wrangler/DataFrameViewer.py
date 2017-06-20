
# allows python3 style print function
from __future__ import print_function


__author__      = "Gregory D. Erhardt"
__copyright__   = "Copyright 2013 SFCTA"
__license__     = """
    This file is part of sfdata_wrangler.

    sfdata_wrangler is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    sfdata_wrangler is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with sfdata_wrangler.  If not, see <http://www.gnu.org/licenses/>.
"""

import sys

from qtpandas import DataFrameWidget
from qtpy import QtGui
from qtpy import QtWidgets

class DataFrameViewer():
    """ 
    Provides functionality to view and scroll through a pandas dataframe. 
    
    Note that this is memory intensive, so keep the queries to ~10000 rows. 
    """
                
    def view(self, df): 
        """ 
        View the dataframe and exit cleanly. 
        
        To view a subset of rows, such as 10 to 20, use view(df[10:20])
        """
        
        # need to initialize an application
        app = QtWidgets.QApplication(sys.argv)
        app.aboutToQuit.connect(app.deleteLater)

        # Create the widget and set the DataFrame
        mw = QtWidgets
        df_withIndexView = df.reset_index()
        mw.widget = DataFrameWidget(df_withIndexView)

        # Set the layout
        vbox = QtGui.QVBoxLayout()
        vbox.addWidget(mw.widget)
        mw.setLayout(vbox)
        
        # view
        mw.show()      
        app.exec_()

        # exit nicely
        app.quit()
        