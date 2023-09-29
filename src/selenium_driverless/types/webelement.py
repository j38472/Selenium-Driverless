# Licensed to the Software Freedom Conservancy (SFC) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The SFC licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
# edited by kaliiiiiiiiiii
import time
import traceback
import warnings
import numpy as np

from base64 import b64decode
from collections import defaultdict
from cdp_socket.exceptions import CDPError

# driverless
from selenium_driverless.types.by import By
from selenium_driverless.types.deserialize import JSRemoteObj
from selenium_driverless.scripts.geometry import gen_heatmap, gen_rand_point, centroid


class NoSuchElementException(Exception):
    pass


class StaleElementReferenceException(Exception):
    pass


class ElementNotVisible(Exception):
    pass


class ElementNotInteractable(Exception):
    def __init__(self, x: float, y: float, _type: str = "interactable"):
        super().__init__(f"element not {_type} at x:{x}, y:{y}, it might be hidden under another one")


class ElementNotClickable(ElementNotInteractable):
    def __init__(self, x: float, y: float):
        super().__init__(y, y, _type="clickable")


# noinspection PyProtectedMember
class WebElement(JSRemoteObj):
    """Represents a DOM element.

    Generally, all interesting operations that interact with a document will be
    performed through this interface.

    All method calls will do a freshness check to ensure that the element
    reference is still valid.  This essentially determines whether the
    element is still attached to the DOM.  If this test fails, then an
    ``StaleElementReferenceException`` is thrown, and all future calls to this
    instance will fail.
    """

    def __init__(self, target, obj_id=None,
                 node_id=None, backend_node_id: str = None, loop=None, class_name: str = None,
                 context_id: int = None) -> None:
        self._loop = loop
        if not (obj_id or node_id or backend_node_id):
            raise ValueError("either js, obj_id or node_id need to be specified")
        self._node_id = node_id
        self._backend_node_id = backend_node_id
        self._class_name = class_name
        self._started = False
        self.___context_id__ = context_id
        self._obj_ids = {}
        self._frame_id = None
        if obj_id and context_id:
            self._obj_ids[context_id] = obj_id
        self.___obj_id__ = None
        super().__init__(target=target, obj_id=obj_id)

    def __await__(self):
        return self.__aenter__().__await__()

    async def __aenter__(self):
        if not self._started:
            # noinspection PyUnusedLocal
            async def clear_node_ids(data):
                await self.obj_id
                self._node_id = None
                self._backend_node_id = None

            await self.__target__.add_cdp_listener("Page.loadEventFired", clear_node_ids)
            self._started = True

        return self

    @property
    async def obj_id(self):
        return await self.__obj_id_for_context__()

    async def __obj_id_for_context__(self, context_id: int = None):
        if not context_id:
            context_id = self.__context_id__
        if not self._obj_ids.get(context_id):
            args = {}
            if not (self._node_id or self._backend_node_id):
                await self.obj_id

            if self._node_id:
                args["nodeId"] = self._node_id
            elif self._backend_node_id:
                args["backendNodeId"] = self._backend_node_id
            if context_id:
                args["executionContextId"] = context_id
            res = await self.__target__.execute_cdp_cmd("DOM.resolveNode", args)
            obj_id = res["object"].get("objectId")
            if obj_id:
                if self.__context_id__ == context_id:
                    self.___obj_id__ = obj_id
                self._obj_ids[context_id] = obj_id
            class_name = res["object"].get("className")
            if class_name:
                self._class_name = class_name
        return self._obj_ids.get(context_id)

    @property
    def __context_id__(self):
        if self.__obj_id__:
            return int(self.__obj_id__.split(".")[1])
        else:
            return self.___context_id__

    @property
    async def node_id(self):
        if not self._node_id:
            node = await self.__target__.execute_cdp_cmd("DOM.requestNode", {"objectId": await self.obj_id})
            self._node_id = node["nodeId"]
        return self._node_id

    @property
    async def frame_id(self):
        if not self._frame_id:
            await self._describe()
        return self._frame_id

    @property
    async def content_document(self):
        _type = await self.tag_name
        if _type == "iframe":
            res = await self._describe()
            document = res.get("contentDocument")
            if document:
                # iframe directly accessible
                if not self._loop:
                    return await WebElement(node_id=document["nodeId"], backend_node_id=document["backendNodeId"], target=self.__target__,
                                            loop=self._loop, class_name="HTMLDocument")
                else:
                    from selenium_driverless.sync.webelement import WebElement as SyncWebElement
                    return await SyncWebElement(node_id=document["nodeId"],
                                                backend_node_id=document["backendNodeId"], target=self.__target__,
                                                loop=self._loop, class_name='HTMLDocument')
            else:
                # iframe acessible over another target
                target = await self.__target__.get_targets_for_iframes([self], _warn=False)
                if target:
                    return await target[0]._document_elem

    @property
    async def document_url(self):
        res = await self._describe()
        return res.get('documentURL')

    @property
    async def backend_node_id(self):
        if not self._backend_node_id:
            await self._describe()
        return self._backend_node_id

    @property
    def class_name(self):
        return self._class_name

    async def find_element(self, by: str, value: str, idx: int = 0, timeout: int or None = None):
        """Find an element given a By strategy and locator.

        :Usage:
            ::

                element = element.find_element(By.ID, 'foo')

        :rtype: WebElement
        """
        elems = []
        start = time.monotonic()
        while not elems:
            elems = await self.find_elements(by=by, value=value)
            if (not timeout) or (time.monotonic() - start) > timeout:
                break
        if not elems:
            raise NoSuchElementException()
        return elems[idx]

    async def find_elements(self, by: str = By.ID, value: str or None = None):
        """Find elements given a By strategy and locator.

        :Usage:
            ::

                element = element.find_elements(By.CLASS_NAME, 'foo')

        :rtype: list of WebElement
        """
        from selenium_driverless.types.by import By

        if by == By.ID:
            by = By.XPATH
            value = f'//*[@id="{value}"]'
        elif by == By.CLASS_NAME:
            by = By.XPATH
            value = f'//*[@class="{value}"]'
        elif by == By.NAME:
            by = By.XPATH
            value = f'//*[@name="{value}"]'

        if by == By.TAG_NAME:
            return await self.execute_script("return obj.getElementsByTagName(arguments[0])",
                                             value, serialization="deep", unique_context=True, timeout=10)
        elif by == By.CSS_SELECTOR:
            elems = []
            node_id = await self.node_id
            res = await self.__target__.execute_cdp_cmd("DOM.querySelectorAll", {"nodeId": node_id,
                                                                                 "selector": value}, timeout=2)
            node_ids = res["nodeIds"]
            for node_id in node_ids:
                if self._loop:
                    from selenium_driverless.sync.webelement import WebElement as SyncWebElement
                    elem = SyncWebElement(node_id=node_id, target=self.__target__, loop=self._loop,
                                          context_id=self.__context_id__)
                else:
                    elem = await WebElement(node_id=node_id, target=self.__target__, context_id=self.__context_id__)
                elems.append(elem)
            return elems
        elif by == By.XPATH:
            scipt = """return document.evaluate(
                          arguments[0],
                          obj,
                          null,
                          XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
                          null,
                        );"""
            return await self.execute_script(scipt, value, serialization="deep", timeout=10, unique_context=True)
        else:
            return ValueError("unexpected by")

    async def _describe(self):
        res = await self.__target__.execute_cdp_cmd("DOM.describeNode", {"objectId": await self.obj_id, "pierce": True})
        res = res["node"]
        self._backend_node_id = res["backendNodeId"]
        self._node_id = res["nodeId"]
        self._frame_id = res.get("frameId")

        return res

    async def get_listeners(self, depth: int = 3):
        res = await self.__target__.execute_cdp_cmd(
            "DOMDebugger.getEventListeners", {"objectId": await self.obj_id, "depth": depth, "pierce": True})
        return res['listeners']

    @property
    async def source(self):
        obj_id = await self.obj_id
        res = await self.__target__.execute_cdp_cmd("DOM.getOuterHTML", {"objectId": obj_id})
        return res["outerHTML"]

    async def set_source(self, value: str):
        await self.__target__.execute_cdp_cmd("DOM.setOuterHTML", {"nodeId": await self.node_id, "outerHTML": value})

    async def get_property(self, name: str) -> str or None:
        """Gets the given property of the element.

        :Args:
            - name - Name of the property to retrieve.

        :Usage:
            ::

                text_length = target_element.get_property("text_length")
        """
        return await self.execute_script(f"return obj[arguments[0]]", name)

    @property
    async def tag_name(self) -> str:
        """This element's ``tagName`` property."""
        node = await self._describe()
        return node["localName"]

    @property
    async def text(self) -> str:
        """The text of the element."""
        return await self.get_property("textContent")

    @property
    async def value(self) -> str:
        """The value of the element."""
        return await self.get_property("value")

    async def clear(self) -> None:
        """Clears the text if it's a text entry element."""
        await self.execute_script("obj.value = ''", unique_context=True)

    async def remove(self):
        await self.__target__.execute_cdp_cmd("DOM.removeNode", {"nodeId": await self.node_id})

    async def highlight(self, highlight=True):
        if not self.__target__._dom_enabled:
            await self.__target__.execute_cdp_cmd("DOM.enable")
        if highlight:
            await self.__target__.execute_cdp_cmd("Overlay.enable")
            await self.__target__.execute_cdp_cmd("Overlay.highlightNode", {"objectId": await self.obj_id,
                                                                            "highlightConfig": {
                                                                                "showInfo": True,
                                                                                "borderColor": {
                                                                                    "r": 76, "g": 175, "b": 80, "a": 1
                                                                                },
                                                                                "contentColor": {
                                                                                    "r": 76, "g": 175, "b": 80,
                                                                                    "a": 0.24
                                                                                },
                                                                                "shapeColor": {
                                                                                    "r": 76, "g": 175, "b": 80,
                                                                                    "a": 0.24
                                                                                }
                                                                            }})
        else:
            await self.__target__.execute_cdp_cmd("Overlay.disable")

    async def focus(self):
        return await self.__target__.execute_cdp_cmd("DOM.focus", {"objectId": await self.obj_id})

    async def click(self, timeout: float = None, bias: float = 5, resolution: int = 50, debug: bool = False,
                    scroll_to=True, move_to: bool = True, listener_depth: int = 3) -> None:
        """Clicks the element."""
        if scroll_to:
            await self.scroll_to()

        is_clickable: bool = listener_depth is None
        if not is_clickable:
            for listener in await self.get_listeners(depth=listener_depth):
                _type = listener["type"]
                if _type in ["click", "mousedown", "mouseup"]:
                    is_clickable = True
                    break

        x, y = await self.mid_location(bias=bias, resolution=resolution, debug=debug)
        if not is_clickable:
            raise ElementNotClickable(x, y)

        await self.__target__.pointer.click(x, y=y, click_kwargs={"timeout": timeout}, move_to=move_to)

    async def write(self, text: str):
        await self.focus()
        await self.__target__.execute_cdp_cmd("Input.insertText", {"text": text})

    async def send_keys(self, value: str) -> None:
        # noinspection GrazieInspection
        """Simulates typing into the element.

                :Args:
                    - value - A string for typing, or setting form fields.  For setting
                      file inputs, this could be a local file path.

                Use this to send simple key events or to fill out form fields::

                    form_textfield = target.find_element(By.NAME, 'username')
                    form_textfield.send_keys("admin")

                This can also be used to set file inputs.

                ::

                    file_input = target.find_element(By.NAME, 'profilePic')
                    file_input.send_keys("path/to/profilepic.gif")
                    # Generally it's better to wrap the file path in one of the methods
                    # in os.path to return the actual path to support cross OS testing.
                    # file_input.send_keys(os.path.abspath("path/to/profilepic.gif"))
                """
        # transfer file to another machine only if remote target is used
        # the same behaviour as for java binding
        raise NotImplementedError("you might use elem.write() for inputs instead")

    async def mid_location(self, bias: float = 5, resolution: int = 50, debug: bool = False):
        """
        returns random location in element with probability close to the middle
        """

        box = await self.box_model
        vertices = box["content"]
        if bias and resolution:
            heatmap = gen_heatmap(vertices, num_points=resolution)
            exc = None
            try:
                point = gen_rand_point(vertices, heatmap, bias_value=bias)
                points = np.array([point])
            except Exception as e:
                points = np.array([[100, 100]])
                exc = e
            if debug:
                from selenium_driverless.scripts.geometry import visualize
                visualize(points, heatmap, vertices)
            if exc:
                traceback.print_exc()
                warnings.warn("couldn't get random point based on heatmap")
                point = centroid(vertices)
        else:
            point = centroid(vertices)

        # noinspection PyUnboundLocalVariable
        x = int(point[0])
        y = int(point[1])
        return [x, y]

    async def submit(self):
        """Submits a form."""
        script = (
            "/* submitForm */var form = this;\n"
            'while (form.nodeName != "FORM" && form.parentNode) {\n'
            "  form = form.parentNode;\n"
            "}\n"
            "if (!form) { throw Error('Unable to find containing form element'); }\n"
            "if (!form.ownerDocument) { throw Error('Unable to find owning document'); }\n"
            "var e = form.ownerDocument.createEvent('Event');\n"
            "e.initEvent('submit', true, true);\n"
            "if (form.dispatchEvent(e)) { HTMLFormElement.prototype.submit.call(form) }\n"
        )
        return await self.execute_script(script, unique_context=True)

    @property
    async def dom_attributes(self) -> dict:
        try:
            res = await self.__target__.execute_cdp_cmd("DOM.getAttributes", {"nodeId": await self.node_id})
            attr_list = res["attributes"]
            attributes_dict = defaultdict(lambda: None)

            for i in range(0, len(attr_list), 2):
                key = attr_list[i]
                value = attr_list[i + 1]
                attributes_dict[key] = value
            return attributes_dict
        except CDPError as e:
            if not (e.code == -32000 and e.message == 'Node is not an Element'):
                raise e

    async def get_dom_attribute(self, name: str) -> str or None:
        """Gets the given attribute of the element. Unlike
        :func:`~selenium.webdriver.remote.BaseWebElement.get_attribute`, this
        method only returns attributes declared in the element's HTML markup.

        :Args:
            - name - Name of the attribute to retrieve.

        :Usage:
            ::

                text_length = target_element.get_dom_attribute("class")
        """
        attrs = await self.dom_attributes
        return attrs[name]

    async def set_dom_attribute(self, name: str, value: str):
        await self.__target__.execute_cdp_cmd("DOM.setAttributeValue", {"nodeId": await self.node_id,
                                                                        "name": name, "value": value})

    async def get_attribute(self, name):
        """Gets the given attribute or property of the element.

        This method will first try to return the value of a property with the
        given name. If a property with that name doesn't exist, it returns the
        value of the attribute with the same name. If there's no attribute with
        that name, ``None`` is returned.

        Values which are considered truthy, that is equals "true" or "false",
        are returned as booleans.  All other non-``None`` values are returned
        as strings.  For attributes or properties which do not exist, ``None``
        is returned.

        To obtain the exact value of the attribute or property,
        use :func:`~selenium.webdriver.remote.BaseWebElement.get_dom_attribute` or
        :func:`~selenium.webdriver.remote.BaseWebElement.get_property` methods respectively.

        :Args:
            - name - Name of the attribute/property to retrieve.

        Example::

            # Check if the "active" CSS class is applied to an element.
            is_active = "active" in target_element.get_attribute("class")
        """
        return await self.get_property(name)

    async def is_selected(self) -> bool:
        """Returns whether the element is selected.

        Can be used to check if a checkbox or radio button is selected.
        """
        result = await self.get_attribute("checked")
        if result:
            return True
        else:
            return False

    async def is_enabled(self) -> bool:
        """Returns whether the element is enabled."""
        return not await self.get_property("disabled")

    @property
    async def shadow_root(self):
        """Returns a shadow root of the element if there is one or an error.
        Only works from Chromium 96, Firefox 96, and Safari 16.4 onwards.

        :Returns:
          - ShadowRoot object or
          - NoSuchShadowRoot - if no shadow root was attached to element
        """
        # todo: move to CDP
        return await self.execute_script("return obj.ShadowRoot()")

    # RenderedWebElement Items
    async def is_displayed(self) -> bool:
        """Whether the element is visible to a user."""
        # Only go into this conditional for browsers that don't use the atom themselves
        size = await self.size
        return not (size["height"] == 0 or size["width"] == 0)

    @property
    async def location_once_scrolled_into_view(self) -> dict:
        """THIS PROPERTY MAY CHANGE WITHOUT WARNING. Use this to discover where
        on the screen an element is so that we can click it. This method should
        cause the element to be scrolled into view.

        Returns the top lefthand corner location on the screen, or zero
        coordinates if the element is not visible.
        """
        await self.scroll_to()
        result = await self.rect
        return {"x": round(result["x"]), "y": round(result["y"])}

    async def scroll_to(self, rect: dict = None):
        args = {"objectId": await self.obj_id}
        if rect:
            args["rect"] = rect
        try:
            await self.__target__.execute_cdp_cmd("DOM.scrollIntoViewIfNeeded", args)
            return True
        except CDPError as e:
            if e.code == -32000 and e.message == 'Node is detached from document':
                return False

    @property
    async def size(self) -> dict:
        """The size of the element."""
        box_model = await self.box_model
        return {"height": box_model["height"], "width": box_model["width"]}

    async def value_of_css_property(self, property_name) -> str:
        """The value of a CSS property."""
        raise NotImplementedError("you might use get_attribute instead")

    @property
    async def location(self) -> dict:
        """The location of the element in the renderable canvas."""
        result = await self.rect
        return {"x": round(result["x"]), "y": round(result["y"])}

    @property
    async def rect(self) -> dict:
        """A dictionary with the size and location of the element."""
        # todo: calculate form DOM.getBoxModel
        result = await self.execute_script("return obj.getClientRects()[0].toJSON()", serialization="json",
                                           unique_context=True)
        return result

    @property
    async def box_model(self):
        res = await self.__target__.execute_cdp_cmd("DOM.getBoxModel", {"objectId": await self.obj_id})
        model = res['model']
        keys = ['content', 'padding', 'border', 'margin']
        for key in keys:
            quad = model[key]
            model[key] = np.array([[quad[0], quad[1]], [quad[2], quad[3]], [quad[4], quad[5]], [quad[6], quad[7]]])
        return model

    @property
    async def aria_role(self) -> str:
        """Returns the ARIA role of the current web element."""
        # todo: move to CDP
        return await self.get_property("ariaRoleDescription")

    @property
    async def accessible_name(self) -> str:
        """Returns the ARIA Level of the current webelement."""
        # todo: move to CDP
        return await self.get_property("ariaLevel")

    @property
    async def screenshot_as_base64(self) -> str:
        """Gets the screenshot of the current element as a base64 encoded
        string.

        :Usage:
            ::

                img_b64 = element.screenshot_as_base64
        """
        raise NotImplementedError()

    @property
    async def screenshot_as_png(self) -> bytes:
        """Gets the screenshot of the current element as a binary data.

        :Usage:
            ::

                element_png = element.screenshot_as_png
        """
        res = await self.screenshot_as_base64
        return b64decode(res.encode("ascii"))

    async def screenshot(self, filename) -> bool:
        """Saves a screenshot of the current element to a PNG image file.
        Returns False if there is any IOError, else returns True. Use full
        paths in your filename.

        :Args:
         - filename: The full path you wish to save your screenshot to. This
           should end with a `.png` extension.

        :Usage:
            ::

                element.screenshot('/Screenshots/foo.png')
        """
        if not filename.lower().endswith(".png"):
            warnings.warn(
                "name used for saved screenshot does not match file " "type. It should end with a `.png` extension",
                UserWarning,
            )
        png = await self.screenshot_as_png
        try:
            with open(filename, "wb") as f:
                f.write(png)
        except OSError:
            return False
        finally:
            del png
        return True

    @property
    async def parent(self):
        """The parent of this element"""
        args = {}
        if self._node_id:
            args["nodeId"] = self._node_id
        else:
            args["objectId"] = await self.obj_id
        node: dict = await self._describe()
        node_id = node.get("parentId", None)
        if node_id:
            return WebElement(node_id=node_id, target=self.__target__, context_id=self.__context_id__)

    @property
    def children(self):
        return self.find_elements(By.CSS_SELECTOR, "*")

    async def execute_raw_script(self, script: str, *args, await_res: bool = False, serialization: str = None,
                                 max_depth: int = 2, timeout: float = 2, execution_context_id: str = None,
                                 unique_context: bool = True):
        return await self.__exec_raw__(script, *args, await_res=await_res, serialization=serialization,
                                       max_depth=max_depth, timeout=timeout,
                                       execution_context_id=execution_context_id,
                                       unique_context=unique_context)

    async def execute_script(self, script: str, *args, max_depth: int = 2, serialization: str = None,
                             timeout: float = 2, execution_context_id: str = None, unique_context: bool = True):
        return await self.__exec__(script, *args, max_depth=max_depth, serialization=serialization,
                                   timeout=timeout, unique_context=unique_context,
                                   execution_context_id=execution_context_id)

    async def execute_async_script(self, script: str, *args, max_depth: int = 2, serialization: str = None,
                                   timeout: float = 2, execution_context_id: str = None, unique_context: bool = True):
        return await self.__exec_async__(script, *args, max_depth=max_depth, serialization=serialization,
                                         timeout=timeout, unique_context=unique_context,
                                         execution_context_id=execution_context_id)

    def __repr__(self):
        return f'{self.__class__.__name__}("{self.class_name}", obj_id="{self.__obj_id__}", node_id="{self._node_id}", backend_node_id={self._backend_node_id}, context_id={self.__context_id__})'

    def __eq__(self, other):
        if isinstance(other, WebElement):
            if other.__target__ == self.__target__:
                if other.__obj_id__ and self.__obj_id__:
                    return other.__obj_id__.split(".")[0] == self.__obj_id__.split(".")[0]
                elif other._backend_node_id == self._backend_node_id:
                    return True
                elif other._node_id == self._node_id:
                    return True
        return False

    def __ne__(self, other):
        return not self.__eq__(other)
