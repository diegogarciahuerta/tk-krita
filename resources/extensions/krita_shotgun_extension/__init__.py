from .shotgun_bridge import ShotgunBridge

__author__ = "Diego Garcia Huerta"
__contact__ = "https://www.linkedin.com/in/diegogh/"


# And add the extension to Krita's list of extensions:
app = Krita.instance()

# Instantiate your class:
extension = ShotgunBridge(parent=app)
app.addExtension(extension)
