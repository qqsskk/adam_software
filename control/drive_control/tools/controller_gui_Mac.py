#!/usr/bin/env python
# -*- coding=utf-8 -*-
""" 
  A simple Controller GUI to drive robots and pose heads.
  Copyright (c) 2008-2011 Michael E. Ferguson.  All right reserved.

  Redistribution and use in source and binary forms, with or without
  modification, are permitted provided that the following conditions are met:
      * Redistributions of source code must retain the above copyright
        notice, this list of conditions and the following disclaimer.
      * Redistributions in binary form must reproduce the above copyright
        notice, this list of conditions and the following disclaimer in the
        documentation and/or other materials provided with the distribution.
      * Neither the name of Vanadium Labs LLC nor the names of its 
        contributors may be used to endorse or promote products derived 
        from this software without specific prior written permission.
  
  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
  ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
  WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
  DISCLAIMED. IN NO EVENT SHALL VANADIUM LABS BE LIABLE FOR ANY DIRECT, INDIRECT,
  INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
  LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
  OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
  LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
  OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
  ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

import rospy
import wx

from math import radians

from geometry_msgs.msg import Twist
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64
from arbotix_msgs.srv import Relax
from arbotix_python.joints import *
from adam_msgs.msg import VehicleCmd

from geometry_msgs.msg import TwistStamped

width = 325


class servoSlider():
    def __init__(self, parent, min_angle, max_angle, name, i):
        self.name = name
        if name.find("_joint") > 0:  # remove _joint for display name
            name = name[0:-6]
        self.position = wx.Slider(parent, -1, 0, int(min_angle * 100),
                                  int(max_angle * 100), wx.DefaultPosition,
                                  (150, -1), wx.SL_HORIZONTAL)
        self.enabled = wx.CheckBox(parent, i, name + ":")
        self.enabled.SetValue(False)
        self.position.Disable()

    def setPosition(self, angle):
        self.position.SetValue(int(angle * 100))

    def getPosition(self):
        return self.position.GetValue() / 100.0


class controllerGUI(wx.Frame):
    TIMER_ID = 100

    def __init__(self, parent, debug=False):
        wx.Frame.__init__(
            self,
            parent,
            -1,
            "ArbotiX Controller GUI",
            style=wx.DEFAULT_FRAME_STYLE &
            ~(wx.RESIZE_BORDER | wx.MAXIMIZE_BOX))
        sizer = wx.GridBagSizer(5, 5)

        self.cmdspeedLabel = wx.StaticText(self, -1, "cmdspeed", (100, 0))
        self.hallspeedLabel = wx.StaticText(self, -1, "hallspeed", (200, 0))
        self.hallSubscriber = rospy.Subscriber("/wheel_circles", TwistStamped, self.hallCB)
        self.wheelSpeed = 0;

        # Move Base
        drive = wx.StaticBox(self, -1, 'Move Base')
        drive.SetFont(wx.Font(10, wx.DEFAULT, wx.NORMAL, wx.BOLD))
        driveBox = wx.StaticBoxSizer(drive, orient=wx.VERTICAL)
        self.movebase = wx.Panel(self, size=(width, width - 20))
        self.movebase.SetBackgroundColour('WHITE')
        self.movebase.Bind(wx.EVT_MOTION, self.onMove)
        wx.StaticLine(
            self.movebase,
            -1, (width / 2, 0), (1, width),
            style=wx.LI_VERTICAL)
        wx.StaticLine(self.movebase, -1, (0, width / 2), (width, 1))
        driveBox.Add(self.movebase)
        sizer.Add(driveBox, (0, 0), wx.GBSpan(1, 1),
                  wx.EXPAND | wx.TOP | wx.BOTTOM | wx.LEFT, 5)
        self.forward = 0
        self.turn = 0
        self.X = 0
        self.Y = 0
        self.pub_cmd_vel = rospy.Publisher("/vehicle_cmd", VehicleCmd)
        self.pre_mode = 1
        self.pre_cmd_vel = VehicleCmd()
        self.changing_mode = 0

        # Move Servos
        servo = wx.StaticBox(self, -1, 'Move Servos')
        servo.SetFont(wx.Font(10, wx.DEFAULT, wx.NORMAL, wx.BOLD))
        servoBox = wx.StaticBoxSizer(servo, orient=wx.VERTICAL)
        servoSizer = wx.GridBagSizer(5, 5)

        joint_defaults = getJointsFromURDF()

        i = 0
        dynamixels = rospy.get_param('/arbotix/dynamixels', dict())
        self.servos = list()
        self.publishers = list()
        self.relaxers = list()

        joints = rospy.get_param('/arbotix/joints', dict())
        # create sliders and publishers
        for name in sorted(joints.keys()):
            # pull angles
            min_angle, max_angle = getJointLimits(name, joint_defaults)
            # create publisher
            self.publishers.append(
                rospy.Publisher(name + '/command', Float64, queue_size=5))
            if rospy.get_param('/arbotix/joints/' + name + '/type',
                               'dynamixel') == 'dynamixel':
                self.relaxers.append(
                    rospy.ServiceProxy(name + '/relax', Relax))
            else:
                self.relaxers.append(None)
            # create slider
            s = servoSlider(self, min_angle, max_angle, name, i)
            servoSizer.Add(s.enabled, (i, 0), wx.GBSpan(1, 1),
                           wx.ALIGN_CENTER_VERTICAL)
            servoSizer.Add(s.position, (i, 1), wx.GBSpan(1, 1),
                           wx.ALIGN_CENTER_VERTICAL)
            self.servos.append(s)
            i += 1

        # add everything
        servoBox.Add(servoSizer)
        sizer.Add(servoBox, (0, 1), wx.GBSpan(1, 1),
                  wx.EXPAND | wx.TOP | wx.BOTTOM | wx.RIGHT, 5)
        self.Bind(wx.EVT_CHECKBOX, self.enableSliders)
        # now we can subscribe
        rospy.Subscriber('joint_states', JointState, self.stateCb)

        # timer for output
        self.timer = wx.Timer(self, self.TIMER_ID)
        self.timer.Start(50)
        wx.EVT_CLOSE(self, self.onClose)
        # wx.EVT_TIMER(self, self.TIMER_ID, self.onTimer)
        self.Bind(wx.EVT_TIMER, self.onTimer, self.timer)

        # bind the panel to the paint event
        wx.EVT_PAINT(self, self.onPaint)
        self.dirty = 1
        self.onPaint()

        self.SetSizerAndFit(sizer)
        self.Show(True)

    def onClose(self, event):
        self.timer.Stop()
        self.Destroy()

    def enableSliders(self, event):
        servo = event.GetId()
        if event.IsChecked():
            self.servos[servo].position.Enable()
        else:
            self.servos[servo].position.Disable()
            if self.relaxers[servo]:
                self.relaxers[servo]()

    def stateCb(self, msg):
        for servo in self.servos:
            if not servo.enabled.IsChecked():
                try:
                    idx = msg.name.index(servo.name)
                    servo.setPosition(msg.position[idx])
                except:
                    pass

    def onPaint(self, event=None):
        # this is the wx drawing surface/canvas
        # dc = wx.PaintDC(self.movebase)
        dc = wx.ClientDC(self.movebase)
        dc.Clear()
        # draw crosshairs
        dc.SetPen(wx.Pen("black", 1))
        dc.DrawLine(width / 2, 0, width / 2, width)
        dc.DrawLine(0, width / 2, width, width / 2)
        dc.SetPen(wx.Pen("red", 2))
        dc.SetBrush(wx.Brush('red', wx.SOLID))
        dc.SetPen(wx.Pen("black", 2))
        dc.DrawCircle((width / 2) + self.X * (width / 2),
                      (width / 2) - self.Y * (width / 2), 5)

    def onMove(self, event=None):
        if event.LeftIsDown():
            pt = event.GetPosition()
            if pt[0] > 0 and pt[0] < width and pt[1] > 0 and pt[1] < width:
                self.forward = ((width / 2) - pt[1]) / 2
                self.turn = (pt[0] - (width / 2)) / 2
                self.X = (pt[0] - (width / 2.0)) / (width / 2.0)
                self.Y = ((width / 2.0) - pt[1]) / (width / 2.0)
        else:
            self.forward = 0
            self.Y = 0
            self.turn = 0
            self.X = 0
        self.onPaint()

    def hallCB(self, hallData):
        self.wheelSpeed = hallData.twist.linear.x
        # self.wheelSpeed = hallData.header.seq

    def speedViewer(self, cmdspeed):
        self.cmdspeedLabel.SetLabelText("cmd"+str(cmdspeed))
        self.hallspeedLabel.SetLabelText("hall"+str(self.wheelSpeed))
        # self.label.Size=wx.Size(920,100)

    def onTimer(self, event=None):
        # send joint updates
        for s, p in zip(self.servos, self.publishers):
            if s.enabled.IsChecked():
                d = Float64()
                d.data = s.getPosition()
                p.publish(d)
        # send base updates
        t = VehicleCmd()
        t.header.stamp = rospy.Time.now()
        t.header.frame_id = '/base_link'
        t.ctrl_cmd.speed = self.forward / 25.0
        t.ctrl_cmd.steering_angle = -self.turn / 130.0
        t.steer_cmd = (t.ctrl_cmd.steering_angle -
                       self.pre_cmd_vel.ctrl_cmd.steering_angle) * 20
        self.speedViewer(t.ctrl_cmd.speed)

        if self.pre_mode == 1:
            if t.ctrl_cmd.speed >= 0:
                if t.ctrl_cmd.speed > self.pre_cmd_vel.ctrl_cmd.speed:
                    t.accel_cmd = (t.ctrl_cmd.speed -
                                   self.pre_cmd_vel.ctrl_cmd.speed) * 20
                else:
                    t.brake_cmd = (self.pre_cmd_vel.ctrl_cmd.speed -
                                   t.ctrl_cmd.speed) * 20
            else:
                if t.ctrl_cmd.speed < -1.5:
                    t.ctrl_cmd.speed = 0
                    self.changing_mode = -1
                else:
                    t.ctrl_cmd.speed = 0
                    t.brake_cmd = (self.pre_cmd_vel.ctrl_cmd.speed -
                                   t.ctrl_cmd.speed) * 20
        else:
            if t.ctrl_cmd.speed <= 0:
                if t.ctrl_cmd.speed < self.pre_cmd_vel.ctrl_cmd.speed:
                    t.accel_cmd = (self.pre_cmd_vel.ctrl_cmd.speed -
                                   t.ctrl_cmd.speed) * 20
                else:
                    t.brake_cmd = (t.ctrl_cmd.speed -
                                   self.pre_cmd_vel.ctrl_cmd.speed) * 20
            else:
                if t.ctrl_cmd.speed > 1.5:
                    t.ctrl_cmd.speed = 0.
                    self.changing_mode = 1
                else:
                    t.ctrl_cmd.speed = 0.
                    t.brake_cmd = (t.ctrl_cmd.speed -
                                   self.pre_cmd_vel.ctrl_cmd.speed) * 20
        # 换挡时应回到原点才能真正换挡，否则将导致车辆急冲
        if self.changing_mode != 0 and self.forward == 0:
            self.pre_mode = self.changing_mode
            self.changing_mode = 0
        t.accel_cmd /= 2
        t.brake_cmd /= 2
        t.mode = self.pre_mode
        self.pub_cmd_vel.publish(t)
        self.pre_cmd_vel = t


if __name__ == '__main__':
    # initialize GUI
    rospy.init_node('controllerGUI')
    app = wx.App()
    frame = controllerGUI(None, True)
    app.MainLoop()